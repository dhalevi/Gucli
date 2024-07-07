# File Name convention is camel case - subject to user changes
# pylint: disable-msg=C0103
# Too generic exception handling by the GUI - using the broad exception handler
# pylint: disable-msg=W0703

"""
gucli.pyw: Provide a GUI for any command line tool.

Read command from an ini file (named after this file), parse the ini file
and prepare a GUI command line options. run the sub-command using these options.
Usage: run gucli.pyw

The script is meant to run using a different name (I will use this as an example: json_tool.pyw)
It will look for json_tool.ini for the command line parameters to include.
If this file does not exist, a default one will be generated.

It will then use Gooey to build a working GUI application using the give command line parameters.
Gooey is a wonderful python module that hacks argparse and generate a nice
command line GUI widgets.
see  https://github.com/chriskiehl/Gooey

Note: a default icon will be created, if none exists.
Save a different icon by the name "config_icon.png"
to use another icon image.
Additionally, one can add 'program_icon.png' to set the GUI window icon itself.
"""

# system imports - should no be an issue
import sys
import time
import base64
import traceback
import subprocess
import configparser
from pathlib import Path
from tkinter import messagebox

# GUI control constants, feel free to play with these values
GUI_WINDOW_SIZE = (1000, 700)
GUI_TERMINAL_FONT_FAMILY = (
    'Courier New'  # Other mono space options: 'Consolas' 'System'
)
GUI_REQUIRED_COLUMNS = 2
GUI_OPTIONAL_COLUMNS = 2
GUI_GENERATE_DEFAULT_ICON = True

# Define the default generated ini file (if missing)
DEFAULT_INI_FILE = """
; The root of the app sets the application general setup (command line, title etc.)
; The section name MUST be 'root'
[root]
; 'command' key is mandatory.
command=python -m json.tool
; 'about' key is optional, but please provide something meaningful.
; Gooey supports about 4 lines of description. indent the other lines.
about=A json pretty print tool. It Can also validate integrity.
    This can be a multi-line help description
    Using indentation
; Optional: help flag: the command help flag. usually '--help' or '-h'.
; it will be used for executing the command's own help message
help_flag=--help

; Arguments section:
;
; Each command line parameter has en entry (spawned by order)
; 'flag': the flag to use. optional. (no 'flag' for positional arguments)
; positional arguments are required parameters, flags are optional.
; 'type' key: flag type, and argument hint.
; The supported types are:
;       boolean (default),
;       string, integer,
;       file (read),
;       dir (read),
;       save (file name),
;       choice (require 'choices' option)
; 'help': A help string, new lines can be used with indentation.

; Example: full argument qualification.
; The section name is used as the argument title (for the GUI)
; 'mutex' is used to group mutually exclusive flags, using common 'mutex' key
; Look for other 'mutex' keys to get the idea.

[Indentation Width]
flag=--indent
type=string
help=Separate items with newlines and use this number of spaces for indentation.
mutex=IndentSpaceOrTab

; The indentation can be numeric
;
;[Indentation width]
;flag=--indent
;type=integer
;default=2
;help=Separate items with newlines and use this number of spaces for indentation.
;mutex=IndentSpaceOrTab

; This is just for the sake of completeness. do not set a value
[Test Choice (Demo)]
flag=--test
type=choice
help=Test choices: For completeness. Do not set.
    for json.tool to work, this flag should not be set
choices=One, Two, Three

; Example: minimal argument qualification (type defaults to boolean)
[Sort Keys]
flag=--sort-keys
help=Sort the output of dictionaries alphabetically by key

# Specify the boolean type explicitly, group using 'mutex' key
[Tab]
flag=--tab
type=boolean
help=Separate items with newlines and use tabs for indentation
mutex=IndentSpaceOrTab

[No Indent]
flag=--no-indent
type=boolean
help=No indentation at all
mutex=IndentSpaceOrTab

[Compact]
flag=--compact
type=boolean
help=Comact json, much less readable, shorter for serialization
mutex=IndentSpaceOrTab


; Positional, mandatory argument #1 (required, multiple file selection is enabled)
; Note that the "file" widget supports multiple file selection.
; the file names are give as a space separated string to the command.
[Infile]
type=file
help=Input file name (required)

; positional #2
; The '--' default serves as 'no argument' here, so this argument becomes optional
[Outfile]
type=save
help=Output file name. Optional. can be equal to Input File name
default=--

"""

# some more useful globals
SHOW_COMMAND_HELP = "Show command's original help page"


def error_message(exception, message=None):
    """Display an error message window. use plain Tk message for compatibility."""
    if not message:  # Use the last line of the exception as the message
        message = traceback.format_exc()
    messagebox.showerror('Script Error', f'Error: {exception}\n\nDetails:\n{message}')
    raise exception


# Now, try to import external modules. show a nice messagebox if failed.
try:
    from gooey import Gooey, GooeyParser
except ImportError as _err:
    module_name = (str(_err).split())[-1].replace(
        "'", ""
    )  # Get the last word, remove quotes
    msg = f'Failed to import {module_name};\nPlease run in CLI:    pip install {module_name}'
    error_message(_err, message=msg)


def select_parser_group(config, section, mutex_group_dict, parser):
    """Select parser group - global or a mutex, if required."""
    arg_mutex = config[section].get('mutex', None)
    item = parser  # default parser group
    if arg_mutex:
        if arg_mutex not in mutex_group_dict:
            mutex_group_dict[arg_mutex] = parser.add_mutually_exclusive_group()
        item = mutex_group_dict[arg_mutex]
    return item


def add_argument(parser, config, mutex_group_dict, section):
    """
    Add argument: add to the parser, digested arg values.

    Prepare defaults, then, according to the type, construct the parser
    parameters.
    Finally, add the arguments to the parser.
    """
    # if the type is defined, use it. default to boolean
    # acceptable types: boolean, string, integer, file, save, dir, choice
    arg_flag = config[section].get('flag', '_positional')
    arg_type = config[section].get('type', 'boolean')
    arg_default = config[section].get('default', None)
    # Handle help string - do not borrow from default if exists
    arg_help = config[section].get(
        'help', f'{section} {arg_flag} ({arg_type}) defaults to "{arg_default}"'
    )
    arg_widget = None
    arg_action = None
    arg_choices = None
    # Construct initial arguments dictionary
    arg_dict = {'help': arg_help, 'default': arg_default}

    # type switch case exist in python 3.10, but I wanted previous versions.
    # I will not give up on f'{x}' interpolation from python 3.6
    if arg_type == 'boolean':
        arg_action = 'store_true'
    elif arg_type == 'string':
        arg_action = 'store'
    elif arg_type == 'integer':
        arg_widget = 'IntegerField'
    elif arg_type == 'file':
        arg_widget = "MultiFileChooser"
        arg_dict['nargs'] = '+'  # when a file is required, select at least one file
    elif arg_type == 'save':
        arg_widget = "FileSaver"
    elif arg_type == 'dir':
        arg_widget = "DirChooser"
    elif arg_type == 'choice':
        arg_action = 'store'
        raw_choices = config[section].get('choices', 'Yes, No')
        # Comman separated string to python list, w/o whitespaces
        arg_choices = [ch.strip() for ch in raw_choices.split(',') if ch != '']
    else:  # Default
        arg_action = 'store_true'
        info_box(
            f'Section "{section}": Invalid type "{arg_type}"; defaulting to boolean'
        )

    arg_dict['widget'] = arg_widget
    arg_dict['action'] = arg_action
    if arg_choices:
        arg_dict['choices'] = arg_choices
    # Set the primary argument
    if '_positional' == arg_flag:
        primary_argument = section
    else:  # flags are optional, setup the 'dest' to find the section key
        arg_dict['dest'] = section
        arg_dict['required'] = False
        primary_argument = arg_flag
    # handle mutex group, if any
    item = select_parser_group(config, section, mutex_group_dict, parser)
    # Construct the command line using primary_arg and the option dict
    item.add_argument(primary_argument, **arg_dict)


def build_arg_parser(config):
    """
    Build arguments parser (Gooey widgets) form the current configuration.

    Handle the supported parameters types.
    """
    root = config.defaults()
    # command is mandatory.
    config_command = root['command']
    parser = GooeyParser(description=root.get('about', config_command))
    mutex_group_dict = {}
    for section in config.sections():
        add_argument(parser, config, mutex_group_dict, section)
    # add help flag, if any
    help_flag = root.get('help_flag', None)
    if help_flag:
        parser.add_argument(
            '--mock-command-help-flag',
            help="Execute command's own help info",
            dest=SHOW_COMMAND_HELP,
            action='store_true',
        )
    return parser.parse_args()


def run_command(cmd, timeout=None):
    """Run a long subprocess, print process output as it comes."""
    start_time = time.monotonic()
    print(f'Running: {cmd}')
    retval = 1  # proc.wait would return '0' upon success
    with subprocess.Popen(
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    ) as proc:
        for line in proc.stdout:
            line = line.decode(errors='backslashreplace').rstrip()
            print(line)
        retval = proc.wait(timeout)
        elapsed_time = time.monotonic() - start_time
        status = str(
            f'\n# Done. Command Return Status: {retval}; '
            f'Elapsed time: {elapsed_time:.2f} sec.\n'
        )
        print(status)
    return retval


def construct_and_run(config, args):
    """Construct and run the command line tool."""
    cmd = config.defaults()['command']
    if args.get(SHOW_COMMAND_HELP, False):  # command help, no need for other parameters
        cmd = cmd + ' ' + config.defaults()['help_flag']
    else:  # construct the command paramneters
        for section in config.sections():
            if args.get(section):
                arg_flag = config[section].get('flag', '')
                if arg_flag != '':
                    arg_flag = ' ' + arg_flag
                # 'True' arguments should NOT be added
                cmd_param = ''
                if not "True" == f'{args[section]}':
                    # section can be a list for multi file, stringify it
                    new_param = args[section]
                    if isinstance(new_param, list):
                        new_param = ' '.join(new_param)
                    cmd_param = ' ' + new_param
                cmd = cmd + arg_flag + cmd_param
    retval = run_command(cmd)
    return retval


def info_box(info):
    """Show an information message box."""
    messagebox.showinfo('Script Notice', info)


def set_default_icon():
    """Set a default GUI icon (a Wrench), if no icon file exists.

    Use base64 to store a nice(?) default icon here.
    The following  code snippet is used to encode a your chosen icon file
    into a base64 string that you can paste below.

    ---------- Cut here -------------
    import base64

    with open('config_icon.png', 'rb') as binary_file:
        binary_file_data = binary_file.read()
    base64_encoded_data = base64.b64encode(binary_file_data)
    base64_message = base64_encoded_data.decode('utf-8')
    n = 82  # choose a value that looks best
    chunk = [base64_message[i : i + n] for i in range(0, len(base64_message), n)]

    for line in chunk:
        print(f'"{line}"')
    ---------- Cut here -------------

    """
    icon_file = str(Path(__file__).parent) + '/config_icon.png'
    if GUI_GENERATE_DEFAULT_ICON and not Path(icon_file).exists():
        info_box(
            'Setting a default program icon file (config_icon.png). '
            'Replace by another icon if you wish'
        )
        base64_icon = str(
            "iVBORw0KGgoAAAANSUhEUgAAAEAAAABABAMAAABYR2ztAAAAMFBMVEXsEBf/klsIn+j/5LVAFahATc280O"
            "7+///tp6D/eiD/8g6hSKOwpttZM7PxV1q2dLDHVzQyAAAAEHRSTlP/////////AP//////////hG6+3wAA"
            "AAlwSFlzAAAExAAABMQBPMzUgwAAAqxJREFUSImFlb9r20AUx/UXZHW9GhIv2jqYdrZig2yy+JrFWgz1DY"
            "WS2sm9pHGapTSEDsUUmt5fEMhscOEVDMGphngqVjK0pt36DwQ6mELfnWTJP3TJA+ND99H3ve+7J8mCB8Iy"
            "XP/w7n5g33XvA8TfY+zBCzPw1u0hots3AcJFHVtGBcTe4A5x0whc4y3APzSmIAV4fH6MJRMwxfLriwvC+u"
            "lA28U+AeeIvwwKLpaeEjDFgRkghQJixQB8+zFoUw3uF9/k4n2Pt+FwyYVoNvlsfY1l3salPrRyufXEBhaL"
            "qGtcAHKzdXgUWDYCh1tTxK89PwZaPAR4uATggrotIAZyG9DIqeCClrrkYjFSsyL1JGIvMSAW9iOJeWBRYF"
            "kiUbCblwaFsEB1X0ct8quAdtiW8pFGIRXI076UHyEdoPv4qcwSkWmlpqDbtICUnztpALnYOJCyqzRg1YU2"
            "mX8SKsjM5bLRCMjqErLyTPmwF1PoJki9LeWZbuuqAtf7XSk/tdJT8KiEUMFOBchE15wifzrvYqlI1Yf8QQ"
            "QUqILwuBsjf76T++F+V8SdHI5LMUCykNSoAOGDx26hA8lphhIQDcawcuWw8bPadgioOYFXlKAQPRyi6k0Y"
            "Y5MgSCZKN0c7otp2aZcF9Kv5yUzaHJrxTDrMc65qjP1MnWoCGKN3h/BYSQOdxX3VJqfmv1k7OQrqc1MdB9"
            "lsOAFY1lqHTZqRCxuip0otYbfK6jvWb4s7rMj1w9vIhzJ+uCQTpR3LsjIBq/G09wMBNwr4w0xAwDYVQCnG"
            "qYB4zlibAOF4o7m3nG0nc0A2X1onR+y76ZulewizRqVEwCaVUdzq1dhz6KyqdFo1E6BOUsWYG1J4E5oHz3"
            "FuTDXsbQuH1WHIzZ9mWGfJ0KbGXfEBQET/RmAW/wFQUmn+RQQp2wAAAABJRU5ErkJggg=="
        )
        base64_img_bytes = base64_icon.encode('utf-8')
        decoded_image_data = base64.decodebytes(base64_img_bytes)
        with open(icon_file, 'wb') as write_handle:
            write_handle.write(decoded_image_data)


@Gooey(
    # set program name: file name w/o extension (gooey issue: The 'w' from .pyw remains)
    program_name=Path(__file__).stem,
    image_dir='.',
    default_size=GUI_WINDOW_SIZE,
    terminal_font_family=GUI_TERMINAL_FONT_FAMILY,
    required_cols=GUI_REQUIRED_COLUMNS,
    optional_cols=GUI_OPTIONAL_COLUMNS,
    clear_before_run=True,
)
def main():
    """
    Read the ini file (create it if non exist).

    Add arguments and generate GUI. Execute the command.
    """
    # catch all execptions
    try:
        ini_file_name = Path(__file__).name.rpartition('.')[0] + '.ini'
        if not Path(ini_file_name).exists():
            with open(ini_file_name, 'w', encoding="utf8") as ini_file_w:
                ini_file_w.write(
                    DEFAULT_INI_FILE.replace('__PYTHON__', Path(sys.executable).stem)
                )
                info_box(f'{ini_file_name} does not exist, Generated a default file')

        set_default_icon()
        config = configparser.ConfigParser(default_section='root')
        with open(ini_file_name, encoding="utf8") as ini_file_handle:
            config.read_file(ini_file_handle)

        args = build_arg_parser(config)
        retval = construct_and_run(config, vars(args))
        # final step - return the sub process exit status
        sys.exit(retval)
    except Exception as _exp:
        error_message(_exp)


if __name__ == '__main__':
    main()
