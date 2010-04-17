from pypy.interpreter.mixedmodule import MixedModule 

class Module(MixedModule):
    """Track the installation of commands and plug-ins."""

    interpleveldefs = {
    }

    appleveldefs = {
        'commands' : 'app_commands.COMMANDS',
        'find_commands' : 'app_commands.find_commands',
        'get_mod_path' : 'app_commands.get_mod_path',
        'CommandError' : 'app_commands.CommandError',
        'CommandWrapper' : 'app_commands.CommandWrapper',
        'HelpWrapper' : 'app_commands.HelpWrapper',
    }