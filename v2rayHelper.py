#!/usr/bin/env python3
import argparse
import atexit
import datetime
import fileinput
import hashlib
import json
import logging
import os
import platform
import random
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile
from abc import ABC, abstractmethod
from urllib.error import URLError
from urllib.parse import urlparse

"""
Exception block start
"""


class V2rayHelperException(Exception):
    pass


class UnsupportedPlatformException(V2rayHelperException):
    def __str__(self):
        return 'Unsupported platform: {0}/{1} ({2})'.format(platform.system(), platform.machine(), platform.version())


class ValidationException(V2rayHelperException):
    pass


class InstallingException(V2rayHelperException):
    pass


class UpgradingException(V2rayHelperException):
    pass


class UninstallingException(V2rayHelperException):
    pass


class PrivilegeException(V2rayHelperException):
    pass


class DownloadException(V2rayHelperException):
    pass


class LatestVersionInstalledException(V2rayHelperException):
    pass


class ConformationRequiredException(V2rayHelperException):
    pass


"""
Exception block end
"""


class V2rayAPI:
    def __init__(self):
        self.__json = None
        self.__pre_release = None
        self.__latest_version = None

    def fetch(self):
        api_url = 'https://api.github.com/repos/v2ray/v2ray-core/releases/latest'

        try:
            with urllib.request.urlopen(api_url) as response:
                self.__json = json.loads(response.read().decode('utf8'))
                self.__pre_release = '(pre release)' if self.__json['prerelease'] else ''
                self.__latest_version = self.__json['tag_name']
        except URLError:
            raise DownloadException('Unable to fetch data from API')

    def search(self, __arch_num, __machine):
        for assets in self.__json['assets']:
            if assets['name'].find('{}-{}.zip'.format(platform.system().lower(), __arch_num)) != -1:
                return assets['name']

    def get_latest_version(self):
        return self.__latest_version

    def get_pre_release(self):
        return self.__pre_release


class V2rayHelper:
    def __init__(self):
        self.__arch = platform.architecture()[0]
        self.__machine = platform.machine()
        self.__arch_num = platform.architecture()[0][0:2]
        self.__api = V2rayAPI()

    @staticmethod
    def __is_v2ray_installed__(installed_raise_error=None, not_installed_raise_error=None):
        install_status = is_command_exists('v2ray')

        if install_status and installed_raise_error is not None:
            raise installed_raise_error

        if not install_status and not_installed_raise_error is not None:
            raise not_installed_raise_error

        return install_status

    @staticmethod
    def __get_v2ray_version__():
        def _try():
            return OSHelper.execute_external_command('v2ray --version').split()[1]

        def _except():
            return None

        return closure_try(_try, subprocess.CalledProcessError, _except)

    def __is_valid_combination__(self):
        supported = {
            'pc': ['X86_64', 'I386'],
            'arm': {
                'arm': ['armv7l', 'armv7', 'armv7hf', 'armv7hl'],
                'arm64': ['aarch64']
            }
        }

        # check architecture
        # make it to upper case to maintain the compatibility across all platforms
        if self.__machine.upper() not in supported['pc']:
            for key in supported['arm']:
                if self.__machine in supported['arm'][key]:
                    self.__arch = key
                    return True
        else:
            return True

        raise UnsupportedPlatformException()

    def run(self, args):
        if self.__is_valid_combination__():
            installed = self.__is_v2ray_installed__()
            version = self.__get_v2ray_version__()
            handler = OSUtil.get_os_handler(self.__arch)

            # get information from API
            self.__api.fetch()
            file_name = self.__api.search(self.__arch_num, self.__machine)
            latest_version = self.__api.get_latest_version()

            # display information obtained from api
            logging.info('Hi there, the latest version of v2ray is {} {}'.format(
                latest_version,
                self.__api.get_pre_release())
            )

            # display operating system information
            logging.info('Operating system: {}-{} ({})'.format(
                platform.system().lower(),
                self.__arch_num,
                self.__machine)
            )

            logging.info('Currently installed version: {}...'.format(version))

            # execute
            if args.install:
                if args.force is False:
                    self.__is_v2ray_installed__(
                        installed_raise_error=InstallingException(
                            'v2ray is already installed, use --force to reinstall.')
                    )

                handler.install(latest_version, file_name)
            elif args.upgrade:
                self.__is_v2ray_installed__(
                    not_installed_raise_error=UpgradingException('v2ray must be installed before you can upgrade it.')
                )

                if version != latest_version or args.force:
                    if args.force:
                        logging.info('You already installed the latest version, forced to upgrade')

                        handler.upgrade(latest_version, file_name)
                else:
                    raise LatestVersionInstalledException(
                        'You already installed the latest version, use --force to upgrade.')
            elif args.remove:
                if args.force is False:
                    self.__is_v2ray_installed__(not_installed_raise_error=UninstallingException(
                        'V2ray is not installed, you cannot uninstall it.'))
                handler.remove(args.force)
            elif args.purge:
                handler.purge(args.sure)
            elif args.auto:
                if not installed:
                    handler.install(latest_version, file_name)
                else:
                    if version != latest_version:
                        handler.upgrade(latest_version, file_name)
                    else:
                        raise LatestVersionInstalledException(
                            'You already installed the latest version, use --force to upgrade.')


class OSHandler(ABC):
    def __init__(self, arch):
        super().__init__()
        self.__post_init__()
        self.__arch = arch

    @abstractmethod
    def __post_init__(self):
        pass

    @abstractmethod
    def install(self, version, filename):
        pass

    @abstractmethod
    def upgrade(self, new_version, filename):
        pass

    @abstractmethod
    def remove(self):
        pass

    @abstractmethod
    def purge(self, confirmed):
        pass

    @staticmethod
    @abstractmethod
    def __get_conf_dir__():
        pass

    @staticmethod
    @abstractmethod
    def __get_base_path__():
        pass

    @staticmethod
    def __get_github_file_url__(path):
        return 'https://raw.githubusercontent.com/waf7225/v2rayHelper/master/{}'.format(path)

    @staticmethod
    def __get_meta_data__(version, file_name):
        url = 'https://github.com/v2ray/v2ray-core/releases/download/{}/metadata.txt'.format(version)
        full_path = '/tmp/v2rayHelper/metadata.txt'
        Downloader(url, 'metadata.txt').start()

        result = []
        with open(full_path, 'r+') as file:
            for line in file:
                split = line.split()
                if len(split) == 2 and split[0] == 'File:':
                    if split[1] == file_name:
                        # return size and sha1
                        result = [int(file.readline().split()[1]), file.readline().split()[1]]
                        break

        OSHelper.remove_if_exists(full_path)

        return result

    @staticmethod
    def __get_extracted_path__(filename, version):
        split_folder = filename[0:-4].split('-')
        split_folder.insert(1, version)

        return '-'.join(split_folder)

    @staticmethod
    def __sha1_file__(file_name):
        sha1sum = hashlib.sha1()
        with open(file_name, 'rb') as source:
            block = source.read(2 ** 16)
            while len(block) != 0:
                sha1sum.update(block)
                block = source.read(2 ** 16)

        return sha1sum.hexdigest()

    @staticmethod
    def __extract_file__(path, output):
        with zipfile.ZipFile(path, 'r') as zip_ref:
            zip_ref.extractall(output)

    @staticmethod
    @abstractmethod
    def __place_file__(path_from):
        pass


class UnixLikeHandler(OSHandler, ABC):
    """
    A generic unix like system handler
    """

    def __init__(self, arch, root_required=False):
        super().__init__(arch)
        self.__user_prefix = ''

        if root_required:
            if os.getuid() == 0:
                pass
            else:
                UnixLikeHandler.__relaunch_with_root__()

    def __post_init__(self):
        # clean-up and create temp folder
        OSHelper.remove_if_exists('/tmp/v2rayHelper')
        OSHelper.mkdir('/tmp/v2rayHelper', 0o644)

    @staticmethod
    def __relaunch_with_root__():
        # ask for root privileges
        logging.info('Re-lunching with root privileges...')
        if is_command_exists('sudo'):
            os.execvp('sudo', ['sudo', '/usr/bin/env', 'python3'] + sys.argv)
        elif is_command_exists('su'):
            os.execvp('su', ['su', '-c', ' '.join(['/usr/bin/env python3'] + sys.argv)])
        else:
            raise PrivilegeException('Sorry, cannot gain root privilege.')

    @staticmethod
    @abstractmethod
    def __auto_start_status__(status):
        pass

    @staticmethod
    @abstractmethod
    def __service__(action):
        pass

    @abstractmethod
    def __install_control_script__(self):
        pass

    def __add_user__(self, _user_ame=None):
        name = _user_ame if _user_ame is not None else 'v2ray'

        def _try_group():
            import grp
            grp.getgrnam(name)

        def _try_user():
            import pwd
            pwd.getpwnam(name)

        def _try_add_group():
            OSHelper.execute_external_command('{}groupadd {}'.format(self.__user_prefix, name))

        def _try_add_user():
            # delete the home folder
            OSHelper.remove_if_exists('/var/lib/{}'.format(name))

            create_user = '{0}useradd -md /var/lib/{1} -s /sbin/nologin -g {1} {1}'.format(self.__user_prefix, name)
            OSHelper.execute_external_command(create_user)

        # add group
        closure_try(_try_group, KeyError, _try_add_group)

        # add user
        closure_try(_try_user, KeyError, _try_add_user)

    def __delete_user__(self, _user_ame=None, _delete_group=True):
        name = _user_ame if _user_ame is not None else 'v2ray'

        def _try_delete_user():
            import pwd
            pwd.getpwnam(name)
            OSHelper.execute_external_command('{0}userdel {1}'.format(self.__user_prefix, name))

            # delete if exists
            OSHelper.remove_if_exists('/var/lib/{}'.format(name))

        def _try_delete_group():
            import grp
            grp.getgrnam(name)
            OSHelper.execute_external_command('{}groupdel {}'.format(self.__user_prefix, name))

        def _do_nothing():
            pass

        # delete user
        closure_try(_try_delete_user, KeyError, _do_nothing)

        # delete group
        if _delete_group:
            closure_try(_try_delete_group, KeyError, _do_nothing)

    def __validate_download__(self, filename, meta_data):
        if len(meta_data) != 0:
            # validate size
            file_size = os.path.getsize(filename)
            sha1 = self.__sha1_file__(filename)

            if meta_data[0] != file_size:
                raise ValidationException('Assertion failed. Expect Size {}, got {}.'.format(meta_data[0], file_size))

            if meta_data[1] != sha1:
                raise ValidationException('Assertion failed. Expect SHA1 {}, got {}.'.format(meta_data[1], sha1))

            logging.info('File {} has passed the validation.'.format(os.path.basename(filename)))
        else:
            raise ValidationException('Failed to perform validation, invalid meta data')

    @staticmethod
    def __place_file__(path_from):
        path_to = '/opt/v2ray/'
        executables = ['v2ray', 'v2ctl']

        # remove old file
        OSHelper.remove_if_exists(path_to)

        # move downloaded file to path_to
        shutil.move(path_from, path_to)

        # change file and dir permission
        for root, dirs, files in os.walk(path_to):
            for dir in dirs:
                os.chmod(os.path.join(root, dir), 0o755)
            for file in files:
                if file not in executables:
                    os.chmod(os.path.join(root, file), 0o644)
                else:
                    os.chmod(os.path.join(root, file), 0o777)

        return path_to

    def __download_and_place_v2ray__(self, version, filename):
        meta_data = self.__get_meta_data__(version, filename)
        full_path = '/tmp/v2rayHelper/{}'.format(filename)
        Downloader('https://github.com/v2ray/v2ray-core/releases/download/{}/{}'.format(version, filename),
                   filename).start()
        self.__validate_download__(full_path, meta_data)
        self.__extract_file__(full_path, '/tmp/v2rayHelper/')

        # remove zip file
        OSHelper.remove_if_exists(full_path)

        return self.__place_file__(self.__get_extracted_path__(full_path, version))

    def __base_install__(self, version, filename):
        # download and install
        installed_path = self.__download_and_place_v2ray__(version, filename)

        # create soft link, for linux
        base_path = self.__get_base_path__()
        executables = ['v2ray', 'v2ctl']

        for file in executables:
            full_path = '{}/{}'.format(base_path, file)

            # delete the old symlink
            OSHelper.remove_if_exists(full_path)

            # create symbol link
            os.symlink(installed_path + file, full_path)

        # add user
        self.__add_user__()

        # script
        self.__install_control_script__()
        self.__auto_start_status__('enable')

        # download and place the default config file
        conf_dir = self.__get_conf_dir__()

        # create default configuration file path
        OSHelper.mkdir(conf_dir, 0o755)
        config_file = '{}/config.json'.format(conf_dir)
        new_token = None

        if not os.path.exists(config_file):
            # download config file
            Downloader(self.__get_github_file_url__('misc/config.json'), 'config.json').start()
            shutil.move('/tmp/v2rayHelper/config.json', config_file)

            # replace default value with randomly generated one
            new_token = [str(uuid.uuid4()), str(random.randint(50000, 65535))]
            FileHelper.replace('{}/config.json'.format(conf_dir), [
                ['dbe16381-f905-4b88-946f-dfc21ed9be29', new_token[0]],
                # ['0.0.0.0', str(get_ip())],
                ['12345', new_token[1]]
            ])
        else:
            logging.info('{} is already exists, skip installing config.json'.format(config_file))

        # start v2ray
        self.__service__('start')

        # print message
        logging.info('Successfully installed v2ray-{}'.format(version))

        if new_token is not None:
            logging.info('v2ray is now bind on {}:{}'.format(OSHelper.get_ip(), new_token[1]))
            logging.info('uuid: {}'.format(new_token[0]))
            logging.info('alterId: {}'.format(64))

    def upgrade(self, new_version, filename):
        # download and place file
        self.__download_and_place_v2ray__(new_version, filename)

        # restart v2ray
        self.__service__('restart')
        logging.info('Successfully upgraded to v2ray-{}'.format(new_version))

    def remove(self):
        logging.info('Uninstalling...')
        # stop v2ray process
        try:
            logging.info('Stop v2ray process')
            self.__service__('stop')

            logging.info('Disable auto start')
            self.__auto_start_status__(False)
        except subprocess.CalledProcessError:
            logging.warning('v2ray service file is not found!!!')

        # remove symbol links
        logging.info('Deleting symbol links')
        for name in ['v2ray', 'v2ctl']:
            path = shutil.which(name)
            if path is not None:
                OSHelper.remove_if_exists(path)

        # remove the real installed folder
        logging.info('Deleting v2ray directory')
        OSHelper.remove_if_exists('/opt/v2ray/')
        OSHelper.remove_if_exists('/usr/local/v2ray/')

    def purge(self, confirmed):
        """
        this is a default implementation for purge function
        :param confirmed: Bool
        :return: None
        """
        if confirmed:
            # uninstall first
            self.remove()

            # delete configuration
            logging.info('Deleting configuration file')
            conf_dir = '/etc/v2ray'
            if conf_dir is not None:
                OSHelper.remove_if_exists(conf_dir)

            # delete user/group
            logging.info('Deleting User/Group v2ray')
            self.__delete_user__('v2ray')

            # delete all other file/folders
            logging.info('Deleting all other files')
            OSHelper.remove_if_exists('/etc/systemd/system/v2ray.service')
            OSHelper.remove_if_exists('/usr/local/etc/rc.d/v2ray')
            OSHelper.remove_if_exists('/var/run/v2ray/')
        else:
            raise ConformationRequiredException('error: the following arguments are required: --sure')


class LinuxHandler(UnixLikeHandler):
    def __init__(self, arch):
        super().__init__(arch, True)

    @staticmethod
    def __get_conf_dir__():
        return '/etc/v2ray'

    @staticmethod
    def __get_base_path__():
        return '/usr/bin'

    @staticmethod
    def __auto_start_status__(status):
        """
        :param status: Bool
        :return:
        """
        LinuxHandler.__service__('enable' if status else 'disable')

    @staticmethod
    def __service__(action):
        OSHelper.execute_external_command('systemctl {} v2ray'.format(action))

    def __install_control_script__(self):
        # download systemd controll script
        Downloader(self.__get_github_file_url__('misc/v2ray.service'), 'v2ray.service').start()
        # move this service file to /etc/systemd/system/
        shutil.move('/tmp/v2rayHelper/v2ray.service', '/etc/systemd/system/v2ray.service')

    def install(self, version, filename):
        self.__base_install__(version, filename)


# TODO add legacy linux support
class LegacyLinuxHandler(LinuxHandler):
    """
        for legacy linux which doesn't have systemd support, e.g Centos 6
    """
    pass

    @staticmethod
    def __service__(action):
        OSHelper.execute_external_command('service v2ray {}'.format(action))


class MacOSHandler(UnixLikeHandler):
    def __init__(self, arch):
        super().__init__(arch)

        # check if brew is installed
        if not is_command_exists('brew'):
            raise V2rayHelperException('This script requires Homebrew, please install Homebrew first')

    @staticmethod
    def __get_conf_dir__():
        pass

    @staticmethod
    def __get_base_path__():
        pass

    @staticmethod
    def __auto_start_status__(status):
        pass

    @staticmethod
    def __service__(action):
        OSHelper.execute_external_command('brew services {} v2ray-core'.format(action))

    def __install_control_script__(self):
        pass

    def install(self, version, filename):
        # Install the official tap
        logging.info('Install the official tap...')
        OSHelper.execute_external_command('brew tap v2ray/v2ray')

        # install v2ray
        logging.info('Install v2ray...')
        OSHelper.execute_external_command('brew install v2ray-core')

        # set auto-start
        logging.info('register v2ray to launch at login...')
        OSHelper.execute_external_command('brew services start v2ray-core')

        # print message
        logging.info('Successfully installed v2ray')

    def upgrade(self, new_version, filename):
        # upgrading v2ray
        # logging.info('Install v2ray...')
        # execute_external_command('brew upgrade v2ray-core')
        pass

    def remove(self, force=True):
        pass

    def purge(self, confirmed):
        pass


class FreeBSDHandler(UnixLikeHandler):
    def __init__(self, arch):
        super().__init__(arch, True)
        self.__user_prefix = 'pw '

    @staticmethod
    def __get_base_path__():
        return '/usr/local/bin'

    @staticmethod
    def __get_conf_dir__():
        return '/usr/local/etc/v2ray'

    def __install_control_script__(self):
        Downloader(self.__get_github_file_url__('misc/v2ray.freebsd'), 'v2ray').start()
        path = '/usr/local/etc/rc.d/v2ray'

        shutil.move('/tmp/v2rayHelper/v2ray', path)
        os.chmod(path, 0o555)

        # create folder for pid file
        LinuxHelper.mkdir_chown('/var/run/v2ray/', 0o755, 'v2ray', 'v2ray')

    @staticmethod
    def __auto_start_status__(status):
        rc_file_path = '/etc/rc.conf'

        if status:
            # Enable
            if not FileHelper.contains(rc_file_path, 'v2ray_enable'):
                with open(rc_file_path, 'a+') as file:
                    file.write('\nv2ray_enable="YES"')
        else:
            # Disable
            if FileHelper.contains(rc_file_path, 'v2ray_enable'):
                with open(rc_file_path, 'r+') as file:
                    new_f = file.readlines()
                    file.seek(0)
                    for line in new_f:
                        if 'v2ray_enable' not in line:
                            file.write(line)
                    file.truncate()

    @staticmethod
    def __service__(action):
        OSHelper.execute_external_command('service v2ray {}'.format(action))

    def install(self, version, filename):
        self.__base_install__(version, filename)

    def purge(self, confirmed):
        super().purge(confirmed)


class OpenBSDHandler(UnixLikeHandler):
    def __init__(self, arch):
        super().__init__(arch, True)
        self.__user_prefix = 'pw '

    def purge(self, confirmed):
        super().purge(confirmed)

    @staticmethod
    # TODO
    def __auto_start_status__(status):
        pass

    @staticmethod
    # TODO
    def __service__(action):
        pass

    # TODO
    def __install_control_script__(self):
        pass

    # TODO
    def install(self, version, filename):
        pass

    # TODO
    @staticmethod
    def __get_conf_dir__():
        pass

    # TODO
    @staticmethod
    def __get_base_path__():
        pass


class Downloader:
    def __init__(self, url, file_name, path='/tmp/v2rayHelper'):
        # variable for report hook
        self.__last_reported = 0
        self.__last_displayed = 0
        self.__start_time = 0

        self.__url = url
        self.__file_name = file_name
        self.__path = path

    @staticmethod
    def __format_size__(size, is_speed=False):
        n = 0
        unit = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}

        while size > 1024:
            size /= 1024
            n += 1

        return '{:6.2f} {}B{} '.format(size, unit[n], '/s' if is_speed else '')

    @staticmethod
    def __format_time__(_time, _append=''):
        return '{:.8}{}'.format(str(datetime.timedelta(seconds=_time)), _append)

    @staticmethod
    def __get_remain_tty_width__(occupied):
        _width = 0
        if is_command_exists('stty'):
            _width = int(OSHelper.execute_external_command('stty size').split()[1])

        return _width - occupied if _width > occupied else 0

    def __display_base_name__(self, base_name):
        name_len = len(base_name)

        if name_len > 25:
            if name_len - self.__last_displayed > 25:
                self.__last_displayed += 1
                return base_name[self.__last_displayed - 1: self.__last_displayed + 24]
            else:
                self.__last_displayed = 0
                return base_name
        else:
            return base_name

    def start(self):
        base_name = os.path.basename(urlparse(self.__url).path)
        file_name = self.__file_name if self.__file_name is not None else base_name

        # full path
        full_path = '{}/{}'.format(self.__path, file_name)
        temp_full_path = '{}.{}'.format(full_path, 'v2tmp')

        # delete temp file
        OSHelper.remove_if_exists(temp_full_path)

        # record down start time
        self.__start_time = time.time()

        def __report_hook(block_num, block_size, total_size):
            read_so_far = block_num * block_size
            if total_size > 0:
                duration = int(time.time() - self.__start_time)
                speed = int(read_so_far) / duration if duration != 0 else 1
                percent = read_so_far * 1e2 / total_size
                estimate = int((total_size - read_so_far) / speed) if speed != 0 else 0
                percent = 100.00 if percent > 100.00 else percent

                # clear line if available
                width = self.__get_remain_tty_width__(96)
                basic_format = '\rFetching: {:<25.25s} {:<15s} {:<15.15s} {:<15.15s} {}{:>{width}}'

                if read_so_far < total_size:
                    # report rate 0.1s
                    if abs(time.time() - self.__last_reported) > 0.1:
                        self.__last_reported = time.time()
                        sys.stdout.write(
                            basic_format.format(
                                self.__display_base_name__(base_name), '{:8.2f}%'.format(percent),
                                self.__format_size__(total_size), self.__format_size__(speed, True),
                                self.__format_time__(estimate, ' ETA'), '', width=width)
                        )
                    else:
                        pass
                else:
                    # near the end
                    sys.stdout.write(
                        basic_format.format(
                            base_name, '{:8.2f}%'.format(percent), self.__format_size__(total_size),
                            self.__format_size__(speed, True),
                            self.__format_time__(duration), '', width=width)
                    )

                    sys.stdout.write('\n')
            # total size is unknown
            else:
                # TODO format output
                sys.stdout.write("\r read {}".format(read_so_far))

                sys.stdout.flush()

        try:
            urllib.request.urlretrieve(self.__url, temp_full_path, __report_hook)
        except URLError:
            raise DownloadException('Unable to fetch url: {}'.format(self.__url))

        os.rename(temp_full_path, full_path)


class OSUtil:
    @staticmethod
    def __is(os_name):
        if is_collection(os_name):
            return True if platform.system().lower() in [x.lower() for x in os_name] else False
        else:
            return platform.system().lower() == os_name.lower()

    @staticmethod
    def get_os_handler(__arch):
        if OSUtil.is_freebsd():
            return FreeBSDHandler(__arch)
        elif OSUtil.is_linux():
            return LinuxHandler(__arch)
        elif OSUtil.is_mac():
            return MacOSHandler(__arch)

    @staticmethod
    def is_freebsd():
        return OSUtil.__is('freebsd')

    @staticmethod
    def is_openbsd():
        return OSUtil.__is('openbsd')

    @staticmethod
    def is_netbsd():
        return OSUtil.__is('netbsd')

    @staticmethod
    def is_linux():
        return OSUtil.__is('linux')

    @staticmethod
    def is_mac():
        return OSUtil.__is('Darwin')


class OSHelper:
    @staticmethod
    def execute_external_command(_command, _encoding='utf-8'):
        """
        :param _command: shell command
        :param _encoding: encoding, default utf-8
        :return: execution result
        """
        return subprocess.check_output(_command, shell=True, stderr=subprocess.DEVNULL).decode(_encoding)

    @staticmethod
    def get_ip():
        """
        from https://stackoverflow.com/questions/166506/finding-local-ip-addresses-using-pythons-stdlib

        modified by Kotarou

        :return: ip address
        """
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                # doesn't even have to be reachable
                s.connect(('10.255.255.255', 1))
                ip_address = s.getsockname()[0]
            except:
                ip_address = '127.0.0.1'

        return ip_address

    @staticmethod
    def remove_if_exists(_path):
        if os.path.exists(_path):
            if os.path.isdir(_path):
                shutil.rmtree(_path)
            else:
                os.unlink(_path)

    @staticmethod
    def mkdir(_path, _perm=0o755):
        if not os.path.exists(_path) and not os.path.islink(_path):
            os.mkdir(_path, _perm)


class LinuxHelper(OSHelper):
    @staticmethod
    def chown(_path, _user=None, _group=None):
        if _user is None and _group is None:
            raise RuntimeError

        if _user is not None:
            shutil.chown(_path, user=_user)
        if _group is not None:
            shutil.chown(_path, group=_group)

    @staticmethod
    def mkdir_chown(_path, _perm=0o755, _user=None, _group=None):
        OSHelper.mkdir(_path, _perm)
        LinuxHelper.chown(_path, _user, _group)

    @staticmethod
    def is_systemd():
        return os.path.isdir('/run/systemd/system')


class FileHelper:
    @staticmethod
    def contains(file_name, data):
        with open(file_name) as file:
            for line in file:
                if line.find(data) is not -1:
                    return True

        return False

    @staticmethod
    def replace(_filename, _replace_pair):
        with fileinput.FileInput(_filename, inplace=True) as file:
            for line in file:
                for replace in _replace_pair:
                    line = line.replace(replace[0], replace[1])
                print(line, end='')


def signal_handler(signal_number):
    """
    from http://code.activestate.com/recipes/410666-signal-handler-decorator/

    A decorator to set the specified function as handler for a signal.
    This function is the 'outer' decorator, called with only the (non-function)
    arguments
    """

    # create the 'real' decorator which takes only a function as an argument
    def __decorator(__function):
        signal.signal(signal_number, __function)
        return __function

    return __decorator


def closure_try(__try, __except, __on_except):
    try:
        return __try()
    except __except:
        return __on_except()


def is_command_exists(_command):
    def _try():
        OSHelper.execute_external_command('type {}'.format(_command))
        return True

    def _except():
        return False

    return closure_try(_try, subprocess.CalledProcessError, _except)


def which_command_exists(_commands):
    if is_collection(_commands):
        for command in _commands:
            if is_command_exists(command):
                return command
        return None
    else:
        raise TypeError


def is_collection(_arg):
    return True if hasattr(_arg, '__iter__') and not isinstance(_arg, (str, bytes)) else False


def get_args():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-A', '--auto', action='store_true', default=True, help='automatic mode')
    group.add_argument('-I', '--install', action='store_true', help='install v2ray')
    group.add_argument('-U', '--upgrade', action='store_true', help='upgrade v2ray')
    group.add_argument('-R', '--remove', action='store_true', help='remove v2ray')
    group.add_argument('-P', '--purge', action='store_true', help='remove v2ray and configure file')
    parser.add_argument('--sure', action='store_true', help='confirm action')
    parser.add_argument('--force', action='store_true', help='force to do the selected action')
    parser.add_argument('--debug', action='store_true', help='show all logs')

    return parser.parse_args()


def __init():
    # clean-up and create temp folder
    OSHelper.remove_if_exists('/tmp/v2rayHelper')
    OSHelper.mkdir('/tmp/v2rayHelper', 0o644)


@atexit.register
def __cleanup():
    # delete temp folder
    OSHelper.remove_if_exists('/tmp/v2rayHelper')


@signal_handler(signal.SIGINT)
def __sigint_handler(signum, frame):
    logging.warning('Quitting...')
    exit(signum)


if __name__ == "__main__":
    args = get_args()

    # set logger
    logging.basicConfig(
        format='%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s',
        level=logging.DEBUG if args.debug else logging.INFO,
        handlers=[
            logging.StreamHandler()
        ]
    )

    logging.debug('debug model enabled')

    try:
        helper = V2rayHelper()
        helper.run(args)
    # V2rayHelperException handling
    except V2rayHelperException as e:
        logging.critical(e)
        exit(-1)
