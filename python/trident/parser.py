#!/usr/bin/env python
"""
parser.py is used to parse the output of trident, translating the score lines
into database entries.

This may run as a standalone script or as a module, trident.parser

"""

from trident import TridentException

# Keys to score lines, which begin with the '>' character and are delimited
# by commas
# Pig column field: (query_id:chararray,ref_id:chararray,score:int,
# energy:double,query_coord:chararray,ref_coords:chararray,length:int,
# identity:chararray,similarity:chararray,query_seq:chararray,
# match_seq:chararray,ref_seq:chararray,orientation:chararray,
# match_type:chararray,base_type:chararray)
# Hive value fields: (query_id STRING,ref_id STRING,score INT,energy DOUBLE,
# query_coord STRING,ref_coords STRING,length INT,identity STRING,
# similarity STRING,query_seq STRING,match_seq STRING,ref_seq STRING,
# orientation STRING,match_type STRING,base_type STRING)
score_keys = ['query_id', 'reference_id', 'score', 'energy', 'query_coords',
              'ref_coords', 'length', 'identity', 'similarity', 'query_seq',
              'match_seq', 'reference_seq', 'orientation', 'match_type',
              'base_type', 'query_start', 'query_end', 'ref_start', 'ref_end']

# Keys to the reference sequence description, which is delimited
# by the '|' character
reference_keys = ["chromosome", "chunk", "seg_offset", "seq_size",
                  "chunk_size", "iso_date", "assembly", "species"]


class BrokenScore(TridentException):
    pass


class BrokenLine(BrokenScore):
    pass


def parser_usage():
    """
    Display usage of trident
    """
    from sys import argv
    print("Usage: %s <filename>" % argv[0])
    print("Parses the output of trident")


def zip_reference(score):
    references = score['reference_id'].split('|')
    return dict(zip(reference_keys, references))


def validate_reference(score):
    """
    Takes a score and verifies that
    0.) the score has the correct number of fields
    1.) the score has a "reference_id" value
    2.) the "reference_id" is delimited by '|' characters
    3.) the math of the genome offset is correct

    If the reference data is found to be invalid, an exception is raised.
    Otherwise, the function returns with no return value.

    @param score: Trident Score dict
    @type score: dict
    """
    if len(score) != len(score_keys):
        raise BrokenScore("Invalid number of fields in Trident Score. "
                          "Expected {0} but received {1}"
                          .format(len(score_keys), len(score)))
    if not "reference_id" in score:
        raise BrokenScore("Missing reference section in score")
    if not "|" in score['reference_id']:
        raise BrokenScore("Broken reference section in score.")
    references = zip_reference(score)

    # Check math of chunck offset
    chunk_number = int(references["chunk"])
    chunk_size = int(references["chunk_size"])
    expected_segment_offset = int(references["seg_offset"])

    # 70 bases per line.
    # Chunk size is the number of lines with one line (70) being subtracted
    #  as an overlap between chunks.
    # chunk_number is decremented by one because chunk_number is
    #  one-indexed.
    actual_segment_offset = 70 * chunk_size * (chunk_number - 1) - 70
    if actual_segment_offset == -70:
        # In this case, we have the first chunk. Offset is zero.
        actual_segment_offset = 0

    if actual_segment_offset != expected_segment_offset:
        raise BrokenScore("Segment offset is not the expected value.\n"
                          "Expected: {0}\n"
                          "Computed: {1}".format(expected_segment_offset,
                                                 actual_segment_offset))


def get_reference(score):
    """
    Parses the reference data (see reference_keys) from a score dict.

    @param score: Trident Score dict
    @type score: dict
    @return dict
    """
    if not score:
        return None

    validate_reference(score)
    return zip_reference(score)


def score_dict_to_gff(score):
    if not score:
        return None
    if len(score) != len(score_keys):
        raise BrokenScore("Invalid number of fields in Trident Score. "
                          "Expected {0} but received {1}"
                          .format(len(score_keys), len(score)))

    ref = get_reference(score)

    retval = "%s\t" % ref["chromosome"]
    retval += ".\t"
    retval += "%s\t" % score["base_type"]
    retval += "%d\t%d\t" % (score["ref_start"], score["ref_end"])
    retval += "%d\t" % float(score["score"])
    if score["orientation"] == "parallel":
        retval += "+\t"
    else:
        retval += "-\t"
    retval += ".\t"  # phase. Has no meaning in this context.
    retval += ("Name=%s;Energy=%f;Chr=%s;GenomeStartPos=%s"
               % (score["query_id"], float(score["energy"]),
                  ref["chromosome"], score["ref_start"]))

    return retval


def score_dict_to_str(score):
    """
    Takes a score dict and returns a score string.
    For human friendly formatting, use str_score
    """
    printed_keys = score_keys[:]
    for i in ['query_start', 'query_end', 'ref_start', 'ref_end']:
        printed_keys.remove(i)
    return ">" + ",".join([score[i] for i in printed_keys])


def score_str_to_dict(line, ignore_offset=False):
    """
    Converts a trident score line to a dict mapping the score data type
    to its value.
    Keys are contained in the trident.parser.score_keys list.

    @see: score_keys
    @see: reference_keys
    @param line: Score line
    @type line: str
    @param ignore_offset: Whether or not to use an offset
     with the reference coordinates (Default: False)
    @type ignore_offset: bool
    @return: Score data as a dict
    """
    from sys import stderr

    if len(line) == 0:
        return None
    if line[0] == '>':
        # This is a score line
        line = line[1:]
    if not len(line) or line[0] == '>':
        # Broken line or summary score, respectively
        return None
    line = line.strip()
    tokens = line.split(',')
    # 4: 2x(query_coords) + 2x(ref_coords)
    if len(tokens) != len(score_keys) - 4:
        stderr.write("Invalid score line: \"%s\"\n" % line)
        return None

    score = dict(zip(score_keys, tokens))
    ref_id = score['reference_id']
    if not ignore_offset and "|" in ref_id:
        tokens = ref_id.split('|')
        if len(tokens) < 3:
            stderr.write("Missing sequence offset.\nSequence: %s" % line)
            return None
        if tokens[2].isdigit():
            offset = int(tokens[2])
        else:
            offset = 0
    else:
        offset = 0

    tokens = score['ref_coords'].split(' ')
    if len(tokens) < 2:
        stderr.write("Broken reference coordinates.\n")
        return None

    score['ref_start'] = int(tokens[0]) + offset
    score['ref_end'] = int(tokens[1]) + offset
    tokens = score['query_coords'].split(' ')
    if len(tokens) < 2:
        stderr.write("Broken query coordinates.\n")
        return None

    score['query_start'] = int(tokens[0])
    score['query_end'] = int(tokens[1])
    return score  # End of score_str_to_dict


def parse_file(infile, ignore_offset=False):
    """
    Reads the next line in the file and converts it to a Trident Score Dict
    using score_str_to_dict

    @see: score_str_to_dict
    @param infile: File Object
    @type infile: file
    @param ignore_offset: Whether or not to use an offset
     with the reference coordinates (Default: False)
    @type ignore_offset: bool
    @return: Score dict
    """
    line = infile.readline()
    if not line:  # EOF
        raise StopIteration
    line = line.strip()
    return (score_str_to_dict(line, ignore_offset), line)


def str_score(score):
    """
    Creates a human readable score string. Each data type has its own line
    with the format:
    DATA TYPE: DATA VALUE

    @param score: Score to be rendered to a string
    @type score: dict
    @return: str
    """
    retval = ""
    for name in sorted(score.iterkeys()):
        val = score[name]
        if name == "ref_coords":
            retval += "%s: %d %d\n" % (name, score['ref_start'],
                                       score['ref_end'])
        elif name == "query_coords":
            retval += "%s: %d %d\n" % (name, score['query_start'],
                                       score['query_end'])
        elif name in ['ref_start', 'ref_end', 'query_start', 'query_end']:
            continue
        else:
            retval += "%s: %s\n" % (name, val)
    return retval


class Parser:
    """
    Iterable Trident Output Parser.

    Takes a file object as in its constructor and can iterate through scores
    in the file.
    """
    def __init__(self, infile, ignore_offset=False):
        """
        Parser constructor.

        @param infile: Score file.
        @type infile: file
        @param ignore_offset: Whether or not to use an offset
         with the reference coordinates (Default: False)
        @type ignore_offset: bool
        """
        self.file = infile
        self.last_line = None
        self.ignore_offset = ignore_offset

    def __iter__(self):
        return self

    def next(self):
        """
        next function for Parser as an iterator.

        @return: Next score in the file being parsed. If there is an empty line
         in the file, None is returned.
        """
        (score, line_str) = parse_file(self.file, self.ignore_offset)
        self.last_line = line_str
        return score


def map_input_files(infilenames, key_gen_function, is_hadoop=False):
    """
    Takes a list of input files and uses a key function
    to count hit frequencies.

    @param infilenames: List of file names to be mapped
    @type infilenames: List
    @param key_gen_function: Function that is used to produce a key
     for a given hit.
    @type key_gen_function: Callable Function
    @param is_hadoop: Optional boolean indicating whether or not errors
     should be ignored (with error message). Default: False
    @type is_hadoop: bool
    @return: Dict maping keys to frequencies
    """
    from sys import stdin

    hit_map = {}
    for infilename in infilenames:
        infile = None
        if infilename == "/dev/stdin":
            infile = stdin  # platform niceness
        else:
            infile = open(infilename, "r")
        parser = Parser(infile)
        for hit in parser:
            if not hit:
                if is_hadoop:
                    from sys import stderr
                    stderr.write("reporter:counter:TridentErrors,"
                                 "BrokenLines,1\n")
                    continue
                else:
                    raise BrokenLine("Broken line while parsing score file:"
                                     " %s" % parser.file.name)

            key = key_gen_function(hit)
            if key in hit_map:
                hit_map[key] += 1
            else:
                hit_map[key] = 1
    return hit_map


def main():
    from getopt import getopt, GetoptError
    from sys import argv
    import os.path as OP

    try:
        (opts, args) = getopt(argv[1:], '', [])
    except GetoptError as ge:
        from sys import stderr
        stderr.write("Unknown option '%s'\n" % ge.opt)
        exit(1)

    if len(args) == 0:
        parser_usage()
        exit(1)

    filename = args[0]
    if not OP.isfile(filename):
        print("\"%s\" is not a file\n" % filename)
        parser_usage()
        exit(1)

    with open(filename, 'r') as infile:
        p = Parser(infile)
        for score in p:
            print(str_score(score))


if __name__ == "__main__":
    main()
