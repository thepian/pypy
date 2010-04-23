from optparse import make_option, OptionParser

import installation

installation.COMMAND_DEFAULTS = dict(
    option_list = (
        make_option('--cluster', dest="cluster", help='The name of the active cluster'),
        make_option('--settings',
            help='The Python path to a settings module, e.g. "myproject.settings.main". If this isn\'t provided, the MAESTRO_SETTINGS_MODULE environment variable will be used.'),
        make_option('--pythonpath',
            help='A directory to add to the Python path, e.g. "/home/djangoprojects/myproject".'),
        make_option('--traceback', action='store_true',
            help='Print traceback on exception'),
    ),
    help = '',
    args = ''
)

