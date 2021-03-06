#!/usr/bin/python
import argparse
import os
import platform
import re
import subprocess

DIR = os.path.dirname(os.path.realpath(__file__))

# Select the correct essl_to_glsl executable for this platform
if platform.system() == 'Darwin':
    ESSL_TO_GLSL = os.path.join(DIR, "angle", "essl_to_glsl_osx")
elif platform.system() == 'Linux':
    ESSL_TO_GLSL = os.path.join(DIR, "angle", "essl_to_glsl_linux")
elif platform.system() == 'Windows':
    ESSL_TO_GLSL = os.path.join(DIR, "angle", "essl_to_glsl_win.exe")
else:
    print "Unsupported platform"
    exit(1)

# See README for where to obtain
CGC = os.path.join(DIR, "cgc")

args = {}

# Color terminal output
def color(s, color):
    if args.color:
        return "\033[1;%dm%s\033[1;m" % (color, s)
    else:
        return s

def grey(s):
    return color(s, 30)

def load_shader(shader_file):
    output = ""
    # Keep track of line numbers, #including will result in some corresponding
    # to other files
    line_labels = []
    with open(shader_file, 'r') as f:
        line_num = 1
        for line in f:
            include_match = re.match("#include (.*)", line)
            if include_match:
                include_file = include_match.group(1)
                fullpath = os.path.join(os.path.dirname(shader_file),
                                        include_file)
                (included_shader, included_line_labels) = load_shader(fullpath)
                output += included_shader
                line_labels += included_line_labels
            else:
                output += line
                line_labels.append("%s:%d" % (shader_file, line_num))
            line_num += 1
    return (output, line_labels)


def create_tmp_file(shader_file, prefix_files=[]):
    (filepath, extension) = os.path.splitext(shader_file)
    filename = os.path.split(filepath)[1]
    tmp_file_name = "tmp_%s" % filename + extension

    # Load in actual shader
    (shader, line_labels) = load_shader(shader_file)

    prefix_shader_file = None
    if len(prefix_files) > 0:
        prefix_shader_file = next((f for f in prefix_files if re.search("prefix%s" % extension, f, re.IGNORECASE)), None)

    # Check if marked as RawShader
    if not args.raw and "RawShader" not in shader:
        # Prepend the prefix shader unless we are in raw mode
        if prefix_shader_file is None:
            prefix_shader_file = os.path.join(DIR, "prefix/prefix%s" % extension)
        (prefix_shader, prefix_line_labels) = load_shader(prefix_shader_file)
        shader = prefix_shader + shader
        line_labels = prefix_line_labels + line_labels

    with open(os.path.join(DIR, tmp_file_name), 'w') as f:
        f.write(shader)

    return (tmp_file_name, line_labels)


def shader_info(shader_file, prefix_files=[]):
    extension = os.path.splitext(shader_file)[1]
    if extension == ".vert":
        profile = "gpu_vp"
    else:
        profile = "gpu_fp"
    (tmp_file_name, line_labels) = create_tmp_file(shader_file, prefix_files)
    # Run essl_to_glsl over the shader, reporting any errors
    p = subprocess.Popen([CGC, "-oglsl", "-strict", "-glslWerror", "-profile",
                          profile, os.path.join(DIR, tmp_file_name)],
                         stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    ret_code = p.wait()
    os.remove(os.path.join(DIR, tmp_file_name))

    if ret_code == 0:
        lines = p.stdout.readlines()
        # Discard output at top, not useful
        while len(lines) > 0:
            if "#program main" in lines.pop(0):
                break

        assembly = "".join(lines[:-1])
        if args.assembly:
            print assembly
        count = lines[-1][2:]
        print shader_file, count
    else:
        print 'Error!'
        for line in p.stdout.readlines():
            print line


def validate_shader(shader_file, prefix_files=[]):
    (tmp_file_name, line_labels) = create_tmp_file(shader_file, prefix_files)
    essl_arguments = "-s=w -x=d"
    if platform.system() == 'Windows':
        essl_arguments += " -b=h"

    essl_command = [ESSL_TO_GLSL, essl_arguments, os.path.join(DIR, tmp_file_name)]
    if platform.system() == "Windows":
        essl_command = " ".join(essl_command)

    p = subprocess.Popen(essl_command,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    ret_code = p.wait()
    os.remove(os.path.join(DIR, tmp_file_name))

    lines = []
    if p.stdout is not None:
        lines = p.stdout.readlines()

    raw_errors = []
    if len(lines) > 0:
        raw_errors = lines[1:-4]

    if ret_code != 0 and len(raw_errors) > 0:
        raw_errors = lines[1:-4]

        # Write out formatted errors
        error = ""
        for e in raw_errors:
            # Error format is: 'ERROR: 0:<line number>: <error message>
            details = re.match("(?:ERROR|WARNING): 0:(\d+): (.*)", e)
            if details:
                line_number = int(details.group(1))
                line_label = line_labels[line_number-1]
                error_message = details.group(2)
                error_format = grey("%s:: ") + "%s\n"
                error += error_format % (line_label, error_message)

        if len(error) > 0:
            print error
            exit(1)

def standalone():
    parser = argparse.ArgumentParser(description='Validate three.js shaders')
    parser.add_argument('files', metavar='FILE', type=str, nargs='+',
                        help='files to validate')
    parser.add_argument('--color', dest='color', action='store_true',
                        help='Color output')
    parser.add_argument('--no-color', dest='color', action='store_false',
                        help='Color output')
    parser.add_argument('--raw', dest='raw', action='store_true',
                        help='Do not prepend standard THREE.js prefix block')
    parser.add_argument('--write', dest='write', action='store', nargs='?', default=False,
                        help='Write out to file.full.ext')
    parser.add_argument('--compile', dest='compile', action='store_true',
                        help='Print number of instructions according to cgc')
    parser.add_argument('--assembly', dest='assembly', action='store_true',
                        help='Print assembly instructions according to cgc')
    parser.set_defaults(color=True)
    global args
    args = parser.parse_args()
    files = args.files
    bad_extensions = filter(lambda f: not re.match('^\.(vert|frag)$',
                            os.path.splitext(f)[1]), files)
    for f in bad_extensions:
        print "Invalid file: %s, only support .frag and .vert files" % f
        exit(1)

    shader_files = []
    prefix_files = []
    if not args.raw:
        [prefix_files.append(f) for f in files if re.search("prefix\.(vert|frag)$", f, re.IGNORECASE) and f not in prefix_files]
        [shader_files.append(f) for f in files if not re.search("prefix\.(vert|frag)$", f, re.IGNORECASE) and f not in shader_files]
    else:
        shader_files = files

    map(lambda f: validate_shader(f, prefix_files), shader_files)
    if args.compile:
        map(lambda f: shader_info(f, prefix_files), shader_files)

    if args.write or args.write is None:
        for f in files:
            dest_name = f.split('.')
            dest_name.insert(-1, 'full')
            dest_name = ".".join(dest_name)
            if args.write and os.path.isdir(args.write):
                (dest_dir, dest_filename) = os.path.split(dest_name)
                dest_name = os.path.join(args.write, dest_filename)
            with open(dest_name, 'w') as out:
                (shader, lines) = load_shader(f)
                out.write(shader)

if __name__ == "__main__":
    standalone()
