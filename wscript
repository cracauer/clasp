#-*- mode: python; coding: utf-8-unix -*-
#
# USAGE:
#   ./waf distclean configure
#   ./waf [action]_[stage-char][gc-name][_d for debug build]
#   ./waf build_fboehm             # will build most of clasp, except the most memory hungry linking tasks at the end
#   ./waf --jobs 2 install_cboehm  # will build and install cclasp
#   to run with low priority, you can prefix with:
#     nice -n 19 ionice --class 3 ./waf --jobs 2 ...
#
# NOTE: please observe the following best practices:
#
# - do *not* use waf's ant_glob (you can shoot yourself in the feet with it, leading to tasks getting redone unnecessarily)
# - in emacs, you may want to: (add-to-list 'auto-mode-alist '("wscript\\'" . python-mode))
# - waf constructs have strange names; it's better not to assume that you know what something is or does based solely on its name.
#   e.g. node.change_ext() returns a new node instance... you've been warned!

import os, sys, logging
import time, datetime

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

from waflib import Utils, Logs, Task, TaskGen
import waflib.Options
from waflib.Tools import c_preproc
from waflib.Tools.compiler_cxx import cxx_compiler
from waflib.Tools.compiler_c import c_compiler
from waflib.Errors import ConfigurationError

sys.path.append('tools-for-build/')
sys.dont_write_bytecode = True   # avoid littering the dirs with .pyc files

from build_file_lists import *
from wscript_utils import *

# Let's not depend on the locale setting of the host, set it explicitly.
os.environ['LC_ALL'] = os.environ['LANG'] = "C"

# This function enables extra command line options for ./waf --help
def options(ctx):
    ctx.load('compiler_cxx')
    ctx.load('compiler_c')
    ctx.add_option('-d', '--debug', default = False, action = 'store_true', dest = 'DEBUG_WHILE_BUILDING',
                   help = 'Enable debugging during the build itself.')
    ctx.add_option('--commands', '--print-commands', '--dump-commands', action = 'store_true', dest = 'PRINT_EXTERNAL_COMMANDS',
                   help = 'Print the copy-paste ready command line of the external programs that the build process spawns.')
    ctx.add_option('--noscrape', '--no-scrape', default = True, action = 'store_false', dest = 'RUN_THE_SCRAPER',
                   help = 'Skip the running of the scraper.')
    ctx.add_option('--load-cclasp', action = 'store_true', dest = 'LOAD_CCLASP',
                   help = '? Probably some debugging helper to start a REPL with cclasp loaded...')

#
# Global variables for the build
#
top = '.'
out = 'build'
APP_NAME = 'clasp'
DARWIN_OS = 'darwin'
LINUX_OS = 'linux'

STAGE_CHARS = [ 'r', 'i', 'a', 'b', 'f', 'c', 'd' ]

GCS_NAMES = [ 'boehm',
              'mpsprep',
              'mps' ]

CLANG_LIBRARIES = [
            'clangASTMatchers',
            'clangDynamicASTMatchers',
            'clangIndex',
            'clangTooling',
            'clangFormat',
            'clangToolingCore',
            'clangBasic',
            'clangCodeGen',
            'clangDriver',
            'clangFrontend',
            'clangFrontendTool',
            'clangCodeGen',
            'clangRewriteFrontend',
            'clangARCMigrate',
            'clangStaticAnalyzerFrontend',
            'clangFrontend',
            'clangDriver',
            'clangParse',
            'clangSerialization',
            'clangSema',
            'clangEdit',
            'clangStaticAnalyzerCheckers',
            'clangStaticAnalyzerCore',
            'clangAnalysis',
            'clangAST',
            'clangRewrite',
            'clangLex',
            'clangBasic',
 ]

BOOST_LIBRARIES = [
            'boost_filesystem',
            'boost_date_time',
            'boost_program_options',
            'boost_system',
            'boost_iostreams']

def build_extension(bld):
    log.pprint('BLUE', "build_extension()")
    bld.recurse("extensions")

def grovel(bld):
    bld.recurse("extensions")

def update_dependencies(cfg):
    # Specifying only label = "some-tag" will check out that tag into a "detached head", but
    # specifying both label = "master" and revision = "some-tag" will stay on master and reset to that revision.
    def fetch_git_revision(path, url, revision = "", label = "master"):
        ret = os.system("./tools-for-build/fetch-git-revision.sh '%s' '%s' '%s' '%s'" % (path, url, revision, label))
        if ( ret != 0 ):
            raise Exception("Failed to fetch git url %s" % url)

    log.pprint('BLUE', 'update_dependencies()')
    fetch_git_revision("src/lisp/kernel/contrib/sicl",
                       "https://github.com/Bike/SICL.git",
                       "a080c75b0aa17a939b09cb378514cfee7a72a4c0")
    fetch_git_revision("src/lisp/kernel/contrib/Acclimation",
                       "https://github.com/clasp-developers/Acclimation.git",
                       "5e0add45b7c6140e4ab07a2cbfd28964e36e6e48")
    fetch_git_revision("src/mps",
                       "https://github.com/Ravenbrook/mps.git",
                       label = "master", revision = "release-1.115.0")
    fetch_git_revision("src/lisp/modules/asdf",
                       "https://gitlab.common-lisp.net/asdf/asdf.git",
                       label = "master", revision = "3.3.1.2")
    os.system("(cd src/lisp/modules/asdf; make --quiet)")

# run this from a completely cold system with:
# ./waf distclean configure
# ./waf build_impsprep
# ./waf analyze_clasp
# This is the static analyzer - formerly called 'redeye'
def analyze_clasp(cfg):
    run_program_echo("build/boehm/cclasp-boehm",
                     "--feature", "ignore-extensions",
                     "--load",    "sys:modules;clasp-analyzer;run-serial-analyzer.lisp",
                     "--eval",    "(core:quit)")
    print("\n\n\n----------------- proceeding with static analysis --------------------")

def stage_value(ctx,s):
    if ( s == 'r' ):
        sval = -1
    elif ( s == 'i' ):
        sval = 0
    elif ( s == 'a' ):
        sval = 1
    elif ( s == 'b' ):
        sval = 2
    elif ( s == 'c' ):
        sval = 4
    elif ( s == 'd' ):
        sval = 5
    elif ( s == 'f' ):
        sval = 3
    elif ( s == 'rebuild' ):
        sval = 0
    elif ( s == 'dangerzone' ):
        sval = 0
    else:
        ctx.fatal("Illegal stage: %s" % s)
    return sval

# Called for each variant, at the end of the configure phase
def configure_common(cfg,variant):
#    include_path = "%s/%s/%s/src/include/clasp/main/" % (cfg.path.abspath(),out,variant.variant_dir()) #__class__.__name__)
#    cfg.env.append_value("CXXFLAGS", ['-I%s' % include_path])
#    cfg.env.append_value("CFLAGS", ['-I%s' % include_path])
    # These will end up in build/config.h
    cfg.define("EXECUTABLE_NAME",variant.executable_name())
    cfg.define("PREFIX",cfg.env.PREFIX)
    assert os.path.isdir(cfg.env.LLVM_BIN_DIR)
    cfg.define("CLASP_CLANG_PATH", os.path.join(cfg.env.LLVM_BIN_DIR, "clang"))
    cfg.define("APP_NAME",APP_NAME)
    cfg.define("BITCODE_NAME",variant.bitcode_name())
    cfg.define("VARIANT_NAME",variant.variant_name())
    cfg.define("BUILD_STLIB", libraries_as_link_flags_as_string(cfg.env.STLIB_ST,cfg.env.STLIB))
    cfg.define("BUILD_LIB", libraries_as_link_flags_as_string(cfg.env.LIB_ST,cfg.env.LIB))
    log.debug("cfg.env.LINKFLAGS = %s", cfg.env.LINKFLAGS)
    log.debug("cfg.env.LDFLAGS = %s", cfg.env.LDFLAGS)
    cfg.define("BUILD_LINKFLAGS", ' '.join(cfg.env.LINKFLAGS) + ' ' + ' '.join(cfg.env.LDFLAGS))

class variant(object):
    build_with_debug_info = False

    def debug_extension(self):
        return "-d" if self.build_with_debug_info else ""
    def debug_dir_extension(self):
        return "_d" if self.build_with_debug_info else ""
    def executable_name(self,stage=None):
        if ( stage == None ):
            use_stage = self.stage_char
        else:
            use_stage = stage
        if (not (use_stage>='a' and use_stage <= 'z')):
            raise Exception("Bad stage: %s"% use_stage)
        return '%s%s-%s%s' % (use_stage,APP_NAME,self.gc_name,self.debug_extension())
    def fasl_name(self,stage=None):
        if ( stage == None ):
            use_stage = self.stage_char
        else:
            use_stage = stage
        if (not (use_stage>='a' and use_stage <= 'z')):
            raise Exception("Bad stage: %s"% use_stage)
        return 'fasl/%s%s-%s%s-image.fasl' % (use_stage,APP_NAME,self.gc_name,self.debug_extension())
    def fasl_dir(self,stage=None):
        if ( stage == None ):
            use_stage = self.stage_char
        else:
            use_stage = stage
        return 'fasl/%s%s-%s-bitcode' % (use_stage,APP_NAME,self.gc_name)
    def common_lisp_bitcode_name(self,use_human_readable_bitcode,stage=None):
        if ( stage == None ):
            use_stage = self.stage_char
        else:
            use_stage = stage
        if (not (use_stage>='a' and use_stage <= 'z')):
            raise Exception("Bad stage: %s"% use_stage)
        name = 'fasl/%s%s-%s-common-lisp' % (use_stage,APP_NAME,self.gc_name)
        if (use_human_readable_bitcode):
            return name+".ll"
        else:
            return name+".bc"
    def variant_dir(self):
        return "%s%s"%(self.gc_name,self.debug_dir_extension())
    def variant_name(self):
        return self.gc_name
    def bitcode_name(self):
        return "%s%s"%(self.gc_name,self.debug_extension())
    def cxx_all_bitcode_name(self):
        return 'fasl/%s-all-cxx.a' % self.bitcode_name()
    def inline_bitcode_archive_name(self,name):
        return 'fasl/%s-%s-cxx.a' % (self.bitcode_name(),name)
    def inline_bitcode_name(self,name):
        return 'fasl/%s-%s-cxx.bc' % (self.bitcode_name(),name)
    def configure_for_release(self,cfg):
        cfg.define("_RELEASE_BUILD",1)
        cfg.env.append_value('CXXFLAGS', [ '-O3', '-g' ])
        cfg.env.append_value('CFLAGS', [ '-O3', '-g' ])
        if (os.getenv("CLASP_RELEASE_CXXFLAGS") != None):
            cfg.env.append_value('CXXFLAGS', os.getenv("CLASP_RELEASE_CXXFLAGS").split() )
        if (os.getenv("CLASP_RELEASE_LINKFLAGS") != None):
            cfg.env.append_value('LINKFLAGS', os.getenv("CLASP_RELEASE_LINKFLAGS").split())
    def configure_for_debug(self,cfg):
        cfg.define("_DEBUG_BUILD",1)
        cfg.define("DEBUG_ASSERT",1)
        cfg.define("DEBUG_BOUNDS_ASSERT",1)
#        cfg.define("DEBUG_ASSERT_TYPE_CAST",1)  # checks runtime type casts
        cfg.define("CONFIG_VAR_COOL",1)
#        cfg.env.append_value('CXXFLAGS', [ '-O0', '-g' ])
        cfg.env.append_value('CXXFLAGS', [ '-O0', '-g' ])
        log.debug("cfg.env.LTO_FLAG = %s", cfg.env.LTO_FLAG)
        if (cfg.env.LTO_FLAG):
            cfg.env.append_value('LDFLAGS', [ '-Wl','-mllvm', '-O0', '-g' ])
        cfg.env.append_value('CFLAGS', [ '-O0', '-g' ])
        if (os.getenv("CLASP_DEBUG_CXXFLAGS") != None):
            cfg.env.append_value('CXXFLAGS', os.getenv("CLASP_DEBUG_CXXFLAGS").split() )
        if (os.getenv("CLASP_DEBUG_LINKFLAGS") != None):
            cfg.env.append_value('LINKFLAGS', os.getenv("CLASP_DEBUG_LINKFLAGS").split())
    def common_setup(self,cfg):
        if self.build_with_debug_info:
            self.configure_for_debug(cfg)
        else:
            self.configure_for_release(cfg)
        configure_common(cfg, self)
        cfg.write_config_header("%s/config.h"%self.variant_dir(),remove=True)

class boehm_base(variant):
    gc_name = 'boehm'

    def configure_variant(self,cfg,env_copy):
        cfg.define("USE_BOEHM",1)
        if (cfg.env['DEST_OS'] == DARWIN_OS ):
            log.debug("boehm_base cfg.env.LTO_FLAG = %s", cfg.env.LTO_FLAG)
            if (cfg.env.LTO_FLAG):
                cfg.env.append_value('LDFLAGS', '-Wl,-object_path_lto,%s_lib.lto.o' % self.executable_name())
        log.info("Setting up boehm library cfg.env.STLIB_BOEHM = %s ", cfg.env.STLIB_BOEHM)
        log.info("Setting up boehm library cfg.env.LIB_BOEHM = %s", cfg.env.LIB_BOEHM)
        if (cfg.env.LIB_BOEHM == [] ):
            cfg.env.append_value('STLIB',cfg.env.STLIB_BOEHM)
        else:
            cfg.env.append_value('LIB',cfg.env.LIB_BOEHM)
        self.common_setup(cfg)

class boehm(boehm_base):
    def configure_variant(self,cfg,env_copy):
        cfg.setenv(self.variant_dir(), env=env_copy.derive())
        super(boehm,self).configure_variant(cfg,env_copy)

class boehm_d(boehm_base):
    build_with_debug_info = True

    def configure_variant(self,cfg,env_copy):
        cfg.setenv("boehm_d", env=env_copy.derive())
        super(boehm_d,self).configure_variant(cfg,env_copy)

class mps_base(variant):
    def configure_variant(self,cfg,env_copy):
        cfg.define("USE_MPS",1)
        if (cfg.env['DEST_OS'] == DARWIN_OS ):
            if (cfg.env.LTO_FLAG):
                cfg.env.append_value('LDFLAGS', '-Wl,-object_path_lto,%s_lib.lto.o' % self.executable_name())
        self.common_setup(cfg)

class mpsprep(mps_base):
    gc_name = 'mpsprep'

    def configure_variant(self,cfg,env_copy):
        cfg.setenv("mpsprep", env=env_copy.derive())
        cfg.define("RUNNING_GC_BUILDER",1)
        super(mpsprep,self).configure_variant(cfg,env_copy)

class mpsprep_d(mps_base):
    gc_name = 'mpsprep'
    build_with_debug_info = True

    def configure_variant(self,cfg,env_copy):
        cfg.setenv("mpsprep_d", env=env_copy.derive())
        cfg.define("RUNNING_GC_BUILDER",1)
        super(mpsprep_d,self).configure_variant(cfg,env_copy)

class mps(mps_base):
    gc_name = 'mps'
    def configure_variant(self,cfg,env_copy):
        cfg.setenv("mps", env=env_copy.derive())
        super(mps,self).configure_variant(cfg,env_copy)

class mps_d(mps_base):
    gc_name = 'mps'
    build_with_debug_info = True

    def configure_variant(self,cfg,env_copy):
        cfg.setenv("mps_d", env=env_copy.derive())
        super(mps_d,self).configure_variant(cfg,env_copy)

class iboehm(boehm):
    stage_char = 'i'
class aboehm(boehm):
    stage_char = 'a'
class bboehm(boehm):
    stage_char = 'b'
class cboehm(boehm):
    stage_char = 'c'

class iboehm_d(boehm_d):
    stage_char = 'i'
class aboehm_d(boehm_d):
    stage_char = 'a'
class bboehm_d(boehm_d):
    stage_char = 'b'
class cboehm_d(boehm_d):
    stage_char = 'c'

class imps(mps):
    stage_char = 'i'
class amps(mps):
    stage_char = 'a'
class bmps(mps):
    stage_char = 'b'
class cmps(mps):
    stage_char = 'c'

class imps_d(mps_d):
    stage_char = 'i'
class amps_d(mps_d):
    stage_char = 'a'
class bmps_d(mps_d):
    stage_char = 'b'
class cmps_d(mps_d):
    stage_char = 'c'

class impsprep(mpsprep):
    stage_char = 'i'
class ampsprep(mpsprep):
    stage_char = 'a'
class bmpsprep(mpsprep):
    stage_char = 'b'
class cmpsprep(mpsprep):
    stage_char = 'c'

class impsprep_d(mpsprep_d):
    stage_char = 'i'
class ampsprep_d(mpsprep_d):
    stage_char = 'a'
class bmpsprep_d(mpsprep_d):
    stage_char = 'b'
class cmpsprep_d(mpsprep_d):
    stage_char = 'c'

def configure(cfg):
    def update_exe_search_path(cfg):
        llvm_config_binary = cfg.env.LLVM_CONFIG_BINARY
        if (len(llvm_config_binary) == 0):
            try:
                llvm_config_binary = cfg.find_program('llvm-config-5.0')
            except cfg.errors.ConfigurationError:
                cfg.to_log('llvm-config-5.0 was not found (ignoring)')
                # Let's fail if no llvm-config binary has been found
                llvm_config_binary = cfg.find_program('llvm-config')
            llvm_config_binary = llvm_config_binary[0]
            cfg.env["LLVM_CONFIG_BINARY"] = llvm_config_binary
        log.debug("Using llvm-config binary: %s", cfg.env.LLVM_CONFIG_BINARY)
        # Let's prefix the OS's binary search PATH with the configured LLVM bin dir.
        # TODO Maybe it would be better to handle full binary paths explicitly -- if possible at all.
        path = os.getenv("PATH").split(os.pathsep)
        externals_bin_dir = run_llvm_config(cfg, "--bindir")
        path.insert(0, externals_bin_dir)
        cfg.environ["PATH"] = os.pathsep.join(path)
        log.info("PATH has been prefixed with '%s'", externals_bin_dir)
        assert os.path.isdir(externals_bin_dir), "Please provide a valid LLVM_CONFIG_BINARY. See the 'wscript.config.template' file."

    def check_externals_clasp_version(cfg):
        log.debug("check_externals_clasp_version begins, cfg.env.LLVM_CONFIG_BINARY = %s", cfg.env.LLVM_CONFIG_BINARY)
        if (not "externals-clasp" in cfg.env.LLVM_CONFIG_BINARY):
            return
        fin = open(run_llvm_config(cfg, "--prefix") + "/../../makefile", "r")
        externals_clasp_llvm_hash = "0bc70c306ccbf483a029a25a6fd851bc332accff"   # update this when externals-clasp is updated
        correct_version = False
        for x in fin:
            if (externals_clasp_llvm_hash in x):
                correct_version = True
        fin.close()
        if (not correct_version):
            raise Exception("You do not have the correct version of externals-clasp installed - you need the one with the LLVM_COMMIT=%s" % externals_clasp_llvm_hash)

    def load_local_config(cfg):
        if os.path.isfile("./wscript.config"):
            local_environment = {}
            exec(open("./wscript.config").read(), globals(), local_environment)
            cfg.env.update(local_environment)
        else:
            log.warn("There is no 'wscript.config' file - assuming default configuration. See 'wscript.config.template' for further details.")

    #
    # This is where configure(cfg) starts
    #
    log.pprint('BLUE', 'configure()')

    cfg.env["BUILD_ROOT"] = os.path.abspath(top) # KLUDGE there should be a better way than this
    load_local_config(cfg)
    cfg.load("why")
    cfg.check_waf_version(mini = '1.7.5')
    update_exe_search_path(cfg)
    run_llvm_config(cfg, "--version") # make sure we fail early
    check_externals_clasp_version(cfg)

    if (cfg.env.LLVM_CONFIG_BINARY_FOR_LIBS):
        log.warn("Using a separate llvm-config binary for linking with the LLVM libs: %s", cfg.env.LLVM_CONFIG_BINARY_FOR_LIBS)
    else:
        log.debug("Using the same llvm-config binary for linking with the LLVM libs: %s", cfg.env.LLVM_CONFIG_BINARY)
        cfg.env["LLVM_CONFIG_BINARY_FOR_LIBS"] = cfg.env.LLVM_CONFIG_BINARY

    if (cfg.env.LLVM5_ORC_NOTIFIER_PATCH):
        cfg.define("LLVM5_ORC_NOTIFIER_PATCH",1)
    if (cfg.env.USE_PARALLEL_BUILD):
        cfg.define("USE_PARALLEL_BUILD",1)
    cfg.env["LLVM_BIN_DIR"] = run_llvm_config(cfg, "--bindir")
    cfg.env["LLVM_AR_BINARY"] = "%s/llvm-ar" % cfg.env.LLVM_BIN_DIR
#    cfg.env["LLVM_AR_BINARY"] = cfg.find_program("llvm-ar", var = "LLVM_AR")[0]
    cfg.env["GIT_BINARY"] = cfg.find_program("git", var = "GIT")[0]
    log.debug("cfg.env['LTO_OPTION'] = %s", cfg.env['LTO_OPTION'])
    if (cfg.env['LTO_OPTION']==[] or cfg.env['LTO_OPTION']=='thinlto'):
        cfg.env.LTO_FLAG = '-flto=thin'
        if (cfg.env['DEST_OS'] == LINUX_OS ):
            cfg.env.append_value('LINKFLAGS', '-Wl,-plugin-opt,cache-dir=/tmp')
        elif (cfg.env['DEST_OS'] == DARWIN_OS ):
            cfg.env.append_value('LINKFLAGS', '-Wl,-cache_path_lto,/tmp')
    elif (cfg.env['LTO_OPTION']=='lto'):
        cfg.env.LTO_FLAG = '-flto'
    elif (cfg.env['LTO_OPTION']=='obj'):
        cfg.env.LTO_FLAG = []
    else:
        raise Exception("LTO_OPTION can only be 'thinlto'(default), 'lto', or 'obj' - you provided %s" % cfg.env['LTO_OPTION'])
    log.info("default cfg.env.LTO_OPTION = %s, final cfg.env.LTO_FLAG = '%s'", cfg.env.LTO_OPTION, cfg.env.LTO_FLAG)

    # find a lisp for the scraper
    if not cfg.env.SCRAPER_LISP:
        cfg.env["SBCL"] = cfg.find_program("sbcl", var = "SBCL")[0]
        cfg.env["SCRAPER_LISP"] = [cfg.env.SBCL,
                                   '--noinform', '--dynamic-space-size', '2048', '--lose-on-corruption', '--disable-ldb', '--end-runtime-options',
                                   '--disable-debugger', '--no-userinit', '--no-sysinit']
    global cxx_compiler, c_compiler
    cxx_compiler['linux'] = ["clang++"]
    c_compiler['linux'] = ["clang"]
    cfg.load('compiler_cxx')
    cfg.load('compiler_c')
### Without these checks the following error happens: AttributeError: 'BuildContext' object has no attribute 'variant_obj'
    cfg.check_cxx(lib='gmpxx gmp'.split(), cflags='-Wall', uselib_store='GMP')
    try:
        cfg.check_cxx(stlib='gc', cflags='-Wall', uselib_store='BOEHM')
    except ConfigurationError:
        cfg.check_cxx(lib='gc', cflags='-Wall', uselib_store='BOEHM')
    #libz
    cfg.check_cxx(lib='z', cflags='-Wall', uselib_store='Z')
    if (cfg.env['DEST_OS'] == LINUX_OS ):
        cfg.check_cxx(lib='dl', cflags='-Wall', uselib_store='DL')
    cfg.check_cxx(lib='ncurses', cflags='-Wall', uselib_store='NCURSES')
#    cfg.check_cxx(stlib='lldb', cflags='-Wall', uselib_store='LLDB')
    cfg.check_cxx(lib='m', cflags='-Wall', uselib_store='M')
    if (cfg.env['DEST_OS'] == DARWIN_OS ):
        pass
    elif (cfg.env['DEST_OS'] == LINUX_OS ):
        pass
        cfg.check_cxx(lib='gcc_s', cflags='-Wall', uselib_store="GCC_S")
        cfg.check_cxx(lib='unwind-x86_64', cflags='-Wall', uselib_store='UNWIND_X86_64')
        cfg.check_cxx(lib='unwind', cflags='-Wall', uselib_store='UNWIND')
        cfg.check_cxx(lib='lzma', cflags='-Wall', uselib_store='LZMA')
    else:
        pass
    cfg.check_cxx(stlib=BOOST_LIBRARIES, cflags='-Wall', uselib_store='BOOST')
    cfg.extensions_include_dirs = []
    cfg.extensions_gcinterface_include_files = []
    cfg.extensions_stlib = []
    cfg.extensions_lib = []
    cfg.extensions_names = []
    cfg.recurse('extensions')
    log.debug("cfg.extensions_names before sort = %s", cfg.extensions_names)
    cfg.extensions_names = sorted(cfg.extensions_names)
    log.debug("cfg.extensions_names after sort = %s", cfg.extensions_names)
    clasp_gc_filename = "clasp_gc.cc"
    if (len(cfg.extensions_names) > 0):
        clasp_gc_filename = "clasp_gc_%s.cc" % ("_".join(cfg.extensions_names))
    log.debug("clasp_gc_filename = %s", clasp_gc_filename)
    cfg.define("CLASP_GC_FILENAME",clasp_gc_filename)
    llvm_liblto_dir = run_llvm_config(cfg, "--libdir")
    llvm_lib_dir = run_llvm_config_for_libs(cfg, "--libdir")
    log.debug("llvm_lib_dir = %s", llvm_lib_dir)
    cfg.env.append_value('LINKFLAGS', ["-L%s" % llvm_lib_dir])
    llvm_libraries = [ x[2:] for x in run_llvm_config_for_libs(cfg, "--libs").split()] # drop the '-l' prefixes
#dynamic llvm/clang
    cfg.check_cxx(lib=llvm_libraries, cflags = '-Wall', uselib_store = 'LLVM', libpath = llvm_lib_dir )
    cfg.check_cxx(lib=CLANG_LIBRARIES, cflags='-Wall', uselib_store='CLANG', libpath = llvm_lib_dir )
#static llvm/clang
#    cfg.check_cxx(stlib=llvm_libraries, cflags = '-Wall', uselib_store = 'LLVM', stlibpath = llvm_lib_dir )
#    cfg.check_cxx(stlib=CLANG_LIBRARIES, cflags='-Wall', uselib_store='CLANG', stlibpath = llvm_lib_dir )
    llvm_include_dir = run_llvm_config_for_libs(cfg, "--includedir")
    log.debug("llvm_include_dir = %s", llvm_include_dir)
    cfg.env.append_value('CXXFLAGS', ['-I./', '-I' + llvm_include_dir])
    cfg.env.append_value('CFLAGS', ['-I./'])
    if (cfg.env['DEST_OS'] == LINUX_OS):
        cfg.env.append_value('CXXFLAGS',['-fno-omit-frame-pointer', '-mno-omit-leaf-frame-pointer'])
        cfg.env.append_value('CFLAGS',['-fno-omit-frame-pointer', '-mno-omit-leaf-frame-pointer'])
    if (cfg.env["PROFILING"] == True):
        cfg.env.append_value('CXXFLAGS',["-pg"])
        cfg.env.append_value('CFLAGS',["-pg"])
        cfg.define("ENABLE_PROFILING",1)
#    if ('program_name' in cfg.__dict__):
#        pass
#    else:
#        cfg.env.append_value('CXXFLAGS', ['-I%s/include/clasp/main/'% cfg.path.abspath() ])
# Check if GC_enumerate_reachable_objects_inner is available
# If so define  BOEHM_GC_ENUMERATE_REACHABLE_OBJECTS_INNER_AVAILABLE
#
    if (cfg.env["BOEHM_GC_ENUMERATE_REACHABLE_OBJECTS_INNER_AVAILABLE"] == True):
        cfg.define("BOEHM_GC_ENUMERATE_REACHABLE_OBJECTS_INNER_AVAILABLE",1)
    cfg.define("USE_CLASP_DYNAMIC_CAST",1)
    cfg.define("BUILDING_CLASP",1)
    log.debug("cfg.env['DEST_OS'] == %s", cfg.env['DEST_OS'])
    if (cfg.env['DEST_OS'] == DARWIN_OS ):
        cfg.define("_TARGET_OS_DARWIN",1)
        cfg.define("USE_LIBUNWIND",1) # use LIBUNWIND
    elif (cfg.env['DEST_OS'] == LINUX_OS ):
        cfg.define("_TARGET_OS_LINUX",1);
#        cfg.define("USE_LIBUNWIND",1) # dont use LIBUNWIND for now
    else:
        raise Exception("Unknown OS %s"%cfg.env['DEST_OS'])
    cfg.define("PROGRAM_CLASP",1)
    cfg.define("CLASP_THREADS",1)
    cfg.define("CLASP_GIT_COMMIT",get_git_commit(cfg))
    cfg.define("CLASP_VERSION",get_clasp_version(cfg))
    cfg.define("CLBIND_DYNAMIC_LINK",1)
    cfg.define("DEFINE_CL_SYMBOLS",1)
#    cfg.define("SOURCE_DEBUG",1)
    cfg.define("USE_SOURCE_DATABASE",1)
    cfg.define("USE_COMPILED_CLOSURE",1)  # disable this in the future and switch to ClosureWithSlots
    cfg.define("CLASP_UNICODE",1)
#    cfg.define("EXPAT",1)
    cfg.define("INCLUDED_FROM_CLASP",1)
    cfg.define("INHERITED_FROM_SRC",1)
    cfg.define("LLVM_VERSION_X100",400)
    cfg.define("LLVM_VERSION","4.0")
    cfg.define("NDEBUG",1)
#    cfg.define("READLINE",1)
#    cfg.define("USE_EXPENSIVE_BACKTRACE",1)
    cfg.define("X86_64",1)
#    cfg.define("DEBUG_FUNCTION_CALL_COUNTER",1)
    cfg.define("_ADDRESS_MODEL_64",1)
    cfg.define("__STDC_CONSTANT_MACROS",1)
    cfg.define("__STDC_FORMAT_MACROS",1)
    cfg.define("__STDC_LIMIT_MACROS",1)
#    cfg.env.append_value('CXXFLAGS', ['-v'] )
#    cfg.env.append_value('CFLAGS', ['-v'] )
    cfg.env.append_value('LINKFLAGS', ['-v'] )
#    includes = [ 'include/' ]
#    includes = includes + cfg.plugins_include_dirs
#    includes_from_build_dir = []
#    for x in includes:
#        includes_from_build_dir.append("-I%s/%s"%(cfg.path.abspath(),x))
#    cfg.env.append_value('CXXFLAGS', includes_from_build_dir )
#    cfg.env.append_value('CFLAGS', includes_from_build_dir )
#    log.debug("DEBUG includes_from_build_dir = %s", includes_from_build_dir)
    cfg.env.append_value('CXXFLAGS', [ '-std=c++11'])
#    cfg.env.append_value('CXXFLAGS', ["-D_GLIBCXX_USE_CXX11_ABI=1"])
    if (cfg.env.LTO_FLAG):
        cfg.env.append_value('CXXFLAGS', cfg.env.LTO_FLAG )
        cfg.env.append_value('CFLAGS', cfg.env.LTO_FLAG )
        cfg.env.append_value('LINKFLAGS', cfg.env.LTO_FLAG )
    if (cfg.env['DEST_OS'] == LINUX_OS ):
        if (cfg.env['USE_LLD']):
            cfg.env.append_value('LINKFLAGS', '-fuse-ld=lld-5.0')
            log.info("Using the lld linker")
        else:
            cfg.env.append_value('LINKFLAGS', '-fuse-ld=gold')
            log.info("Using the gold linker")
        cfg.env.append_value('LINKFLAGS', ['-stdlib=libstdc++'])
        cfg.env.append_value('LINKFLAGS', ['-lstdc++'])
        cfg.env.append_value('LINKFLAGS', '-pthread')
    elif (cfg.env['DEST_OS'] == DARWIN_OS ):
        cfg.env.append_value('LINKFLAGS', ['-Wl,-export_dynamic'])
        lto_library_name = cfg.env.cxxshlib_PATTERN % "LTO"  # libLTO.<os-dep-extension>
        lto_library = "%s/%s" % ( llvm_liblto_dir, lto_library_name)
        cfg.env.append_value('LINKFLAGS',["-Wl,-lto_library,%s" % lto_library])
        cfg.env.append_value('LINKFLAGS', ['-lc++'])
        cfg.env.append_value('LINKFLAGS', ['-stdlib=libc++'])
        cfg.env.append_value('INCLUDES', '/usr/local/Cellar/libunwind-headers/35.3/include')  # brew install libunwind-headers
    cfg.env.append_value('INCLUDES', [ run_llvm_config(cfg,"--includedir") ])
    cfg.env.append_value('INCLUDES', ['/usr/include'] )
    cfg.define("ENABLE_BACKTRACE_ARGS",1)
# --------------------------------------------------
# --------------------------------------------------
# --------------------------------------------------
#
# The following debugging flags slow down clasp
#  They should be disabled in production code
# 
    if (cfg.env.ADDRESS_SANITIZER):
        cfg.env.append_value('CXXFLAGS', ['-fsanitize=address'] )
        cfg.env.append_value('LINKFLAGS', ['-fsanitize=address'])
    if (cfg.env.DEBUG_GUARD):
        cfg.define("DEBUG_GUARD",1)
        cfg.define("DEBUG_GUARD_VALIDATE",1)
    if (cfg.env.DEBUG_GUARD_EXHAUSTIVE_VALIDATE):
        cfg.define("DEBUG_GUARD_EXHAUSTIVE_VALIDATE",1)
    cfg.define("DEBUG_TRACE_INTERPRETED_CLOSURES",1)
    cfg.define("DEBUG_ENVIRONMENTS",1)
#    cfg.define("DEBUG_RELEASE",1)   # Turn off optimization for a few C++ functions; undef this to optimize everything
#    cfg.define("DEBUG_CACHE",1)      # Debug the dispatch caches - see cache.cc
#    cfg.define("DEBUG_BITUNIT_CONTAINER",1)  # prints debug info for bitunit containers
#    cfg.define("DEBUG_ZERO_KIND",1);
#    cfg.define("DEBUG_FLOW_CONTROL",1)  # broken - probably should be removed unless it can be
#    cfg.define("DEBUG_RETURN_FROM",1)   # broken
#    cfg.define("DEBUG_LEXICAL_DEPTH",1) # Generate tests for lexical closure depths
#    cfg.define("DEBUG_FLOW_TRACKER",1)  # record small backtraces to track flow
#    cfg.define("DEBUG_DYNAMIC_BINDING_STACK",1)
#    cfg.define("DEBUG_VALUES",1)   # turn on printing (values x y z) values when core:*debug-values* is not nil
#    cfg.define("DEBUG_IHS",1)
    cfg.define("DEBUG_TRACK_UNWINDS",1)  # Count cc_unwind calls and report in TIME
#    cfg.define("DEBUG_NO_UNWIND",1)
#    cfg.define("DEBUG_STARTUP",1)
#    cfg.define("DEBUG_ACCESSORS",1)
#    cfg.define("DEBUG_GFDISPATCH",1)
##  Generate per-thread logs in /tmp/dispatch-history/**  of the slow path of fastgf
#    cfg.define("DEBUG_CMPFASTGF",1)  # debug dispatch functions by inserting code into them that traces them
#    cfg.define("DEBUG_FASTGF",1)   # generate slow gf dispatch logging and write out dispatch functions to /tmp/dispatch-history-**
#    cfg.define("DEBUG_REHASH_COUNT",1)   # Keep track of the number of times each hash table has been rehashed
#    cfg.define("DEBUG_MONITOR",1)   # generate logging messages to a file in /tmp for non-hot code
#    cfg.define("DEBUG_MEMORY_PROFILE",1)  # Profile memory allocations
    cfg.define("DEBUG_BCLASP_LISP",1)  # Generate debugging frames for all bclasp code - like declaim
    cfg.define("DEBUG_CCLASP_LISP",1)  # Generate debugging frames for all cclasp code - like declaim
#    cfg.define("DEBUG_LONG_CALL_HISTORY",1)
#    cfg.define("DONT_OPTIMIZE_BCLASP",1)  # Optimize bclasp by editing llvm-ir
#    cfg.define("DEBUG_BOUNDS_ASSERT",1)
#    cfg.define("DEBUG_SLOT_ACCESSORS",1)
#    cfg.define("DISABLE_TYPE_INFERENCE",1)
#    cfg.define("DEBUG_THREADS",1)
###  cfg.define("DEBUG_GUARD",1) #<<< this is set in wscript.config
#    cfg.define("CONFIG_VAR_COOL",1)
#    cfg.define("DEBUG_ENSURE_VALID_OBJECT",1)  #Defines ENSURE_VALID_OBJECT(x)->x macro - sprinkle these around to run checks on objects
#    cfg.define("DEBUG_QUICK_VALIDATE",1)    # quick/cheap validate if on and comprehensive validate if not
#    cfg.define("DEBUG_MPS_SIZE",1)   # check that the size of the MPS object will be calculated properly by obj_skip
    cfg.env.USE_HUMAN_READABLE_BITCODE=True
    if (cfg.env.USE_HUMAN_READABLE_BITCODE):
        cfg.define("USE_HUMAN_READABLE_BITCODE",1)
    cfg.define("DEBUG_RECURSIVE_ALLOCATIONS",1)
# -----------------
# defines that slow down program execution
#  There are more defined in clasp/include/gctools/configure_memory.h
    cfg.define("DEBUG_SLOW",1)    # Code runs slower due to checks - undefine to remove checks
# ----------

# --------------------------------------------------
# --------------------------------------------------
# --------------------------------------------------
    cfg.env.append_value('CXXFLAGS', ['-Wno-macro-redefined'] )
    cfg.env.append_value('CXXFLAGS', ['-Wno-deprecated-register'] )
    cfg.env.append_value('CXXFLAGS', ['-Wno-expansion-to-defined'] )
    cfg.env.append_value('CXXFLAGS', ['-Wno-return-type-c-linkage'] )
    cfg.env.append_value('CXXFLAGS', ['-Wno-invalid-offsetof'] )
    cfg.env.append_value('CXXFLAGS', ['-Wno-#pragma-messages'] )
    cfg.env.append_value('CXXFLAGS', ['-Wno-inconsistent-missing-override'] )
    cfg.env.append_value('LIBPATH', ['/usr/lib', '/usr/local/lib'])
    cfg.env.append_value('STLIBPATH', ['/usr/lib', '/usr/local/lib'])
    cfg.env.append_value('LINKFLAGS', ['-fvisibility=default'])
    cfg.env.append_value('LINKFLAGS', ['-rdynamic'])
    sep = " "
    cfg.env.append_value('STLIB', cfg.extensions_stlib)
    cfg.env.append_value('LIB', cfg.extensions_lib)
    cfg.env.append_value('STLIB', cfg.env.STLIB_CLANG)
    cfg.env.append_value('STLIB', cfg.env.STLIB_LLVM)
    cfg.env.append_value('STLIB', cfg.env.STLIB_BOOST)
    cfg.env.append_value('STLIB', cfg.env.STLIB_Z)
    if (cfg.env['DEST_OS'] == LINUX_OS ):
        cfg.env.append_value('LIB', cfg.env.LIB_DL)
        cfg.env.append_value('LIB', cfg.env.LIB_GCC_S)
        cfg.env.append_value('LIB', cfg.env.LIB_UNWIND_X86_64)
        cfg.env.append_value('LIB', cfg.env.LIB_UNWIND)
        cfg.env.append_value('LIB', cfg.env.LIB_LZMA)
    cfg.env.append_value('LIB', cfg.env.LIB_CLANG)
    cfg.env.append_value('LIB', cfg.env.LIB_LLVM)
    cfg.env.append_value('LIB', cfg.env.LIB_NCURSES)
    cfg.env.append_value('LIB', cfg.env.LIB_M)
    cfg.env.append_value('LIB', cfg.env.LIB_GMP)
    cfg.env.append_value('LIB', cfg.env.LIB_Z)
    log.debug("cfg.env.STLIB = %s", cfg.env.STLIB)
    log.debug("cfg.env.LIB = %s", cfg.env.LIB)
    env_copy = cfg.env.derive()
    for gc in GCS_NAMES:
        for debug_build in [True, False]:
            variant_name = gc + '_d' if debug_build else gc
            variant_instance = eval("i" + variant_name + "()")
            log.info("Setting up variant: %s", variant_instance.variant_dir())
            variant_instance.configure_variant(cfg, env_copy)
    update_dependencies(cfg)

def pre_build_hook(bld):
    bld.build_start_time = time.time()
    log.info('Compilation started at %s', datetime.datetime.now())

def post_build_hook(bld):
    duration = round(time.time() - bld.build_start_time)
    log.info('Compilation finished in %s, at %s', str(datetime.timedelta(seconds = duration)), datetime.datetime.now())

def build(bld):
    def install(dest, files, cwd = bld.path, chmod = None):
        dest = '${PREFIX}/' + dest
        # NOTE: waf bug as of 2.0.6: if you call install_as(some-dir, file), then it chmod's away the x flag from some-dir
        if chmod:
            #print('install_as(%s, %s, ...)' % (dest, files))
            bld.install_as(dest, files, chmod = chmod)
        else:
            #print('install_files(%s, %s, ...)' % (dest, files))
            bld.install_files(dest, files, relative_trick = True, cwd = cwd)

    if not bld.variant:
        bld.fatal("Call waf with build_variant, e.g. 'nice -n19 ./waf --jobs 2 --verbose build_cboehm_d'")

    variant = eval(bld.variant + "()")
    bld.variant_obj = variant

    # Reinitialize logging system with a handler that appends to ./build/variant/build.log
    log.reinitialize(console_level = logging.DEBUG if Logs.verbose >= 1 else logging.INFO,
                     log_file = os.path.join(bld.path.abspath(), out, variant.variant_dir(), "build.log"))

    log.debug('build() starts, options: %s', bld.options)

    bld.add_pre_fun(pre_build_hook);
    bld.add_post_fun(post_build_hook);

    stage = bld.stage
    stage_val = stage_value(bld,bld.stage)
    bld.stage_val = stage_val

    log.pprint('BLUE', 'build(), %s, stage %s=%s%s' %
                (variant.variant_name(),
                 bld.stage,
                 bld.stage_val,
                 ", DEBUG_WHILE_BUILDING" if bld.options.DEBUG_WHILE_BUILDING else ''))

    # Waf groups are basically staging of tasks: all tasks in stage N must finish before any
    # task in stage N+1 can begin. (Don't get fooled by the API, groups are ordered internally.)
    # Tasks are recorded into the current stage which can be set by bld.set_group('stage-name').
    # NOTE: group based ordering overrides the set_input based task dependencies, so be careful
    # not to instantiate tasks into the wrong group.
    bld.add_group('preprocessing')
    bld.add_group('compiling/c++')

    bld.use_human_readable_bitcode = bld.env["USE_HUMAN_READABLE_BITCODE"]
    log.debug("Using human readable bitcode: %s", bld.use_human_readable_bitcode)
    bld.clasp_source_files = collect_clasp_c_source_files(bld)

    bld.clasp_aclasp = collect_aclasp_lisp_files(wrappers = False)
    bld.clasp_bclasp = collect_bclasp_lisp_files()
    bld.clasp_cclasp = collect_cclasp_lisp_files()
    bld.clasp_cclasp_no_wrappers = collect_cclasp_lisp_files(wrappers = False)

    bld.extensions_include_dirs = []
    bld.extensions_include_files = []
    bld.extensions_source_files = []
    bld.extensions_gcinterface_include_files = []
    bld.extensions_builders = []

    bld.bclasp_executable = bld.path.find_or_declare(variant.executable_name(stage='b'))
    bld.cclasp_executable = bld.path.find_or_declare(variant.executable_name(stage='c'))
    bld.asdf_fasl_bclasp = bld.path.find_or_declare("%s/src/lisp/modules/asdf/asdf.fasl" % variant.fasl_dir(stage='b'))
    bld.asdf_fasl_cclasp = bld.path.find_or_declare("%s/src/lisp/modules/asdf/asdf.fasl" % variant.fasl_dir(stage='c'))
    bld.bclasp_fasl = bld.path.find_or_declare(variant.fasl_name(stage='b'))
    bld.cclasp_fasl = bld.path.find_or_declare(variant.fasl_name(stage='c'))
    bld.iclasp_executable = bld.path.find_or_declare(variant.executable_name(stage='i'))

    bld.set_group('compiling/c++')

    bld.recurse('extensions')

    log.info("There are %d extensions_builders", len(bld.extensions_builders))
    for x in bld.extensions_builders:
        x.run()

    bld.set_group('preprocessing')

    #
    # Installing the sources
    #
    clasp_c_source_files = bld.clasp_source_files + bld.extensions_source_files
    install('lib/clasp/', clasp_c_source_files)
    install('lib/clasp/', collect_waf_nodes(bld, 'include/clasp/', suffix = ".h"))
    install('lib/clasp/src/lisp/', collect_waf_nodes(bld, 'src/lisp/', suffix = [".lsp", ".lisp", ".asd"]))

    bld.env = bld.all_envs[bld.variant]
    include_dirs = ['.']
    include_dirs.append("%s/src/main/" % bld.path.abspath())
    include_dirs.append("%s/include/" % bld.path.abspath())
    include_dirs.append("%s/%s/%s/generated/" % (bld.path.abspath(), out, variant.variant_dir()))
    include_dirs = include_dirs + bld.extensions_include_dirs
    log.debug("include_dirs = %s", include_dirs)

    # Without this the parallel ASDF load-op's would step on each other's feet
    if (bld.options.RUN_THE_SCRAPER):
        task = precompile_scraper(env = bld.env)
        task.set_outputs([bld.path.find_or_declare("scraper-precompile-done")])
        bld.add_to_group(task)

    make_pump_tasks(bld, 'src/core/header-templates/', 'clasp/core/')
    make_pump_tasks(bld, 'src/clbind/header-templates/', 'clasp/clbind/')

    task = generate_extension_headers_h(env=bld.env)
    task.set_inputs(bld.extensions_gcinterface_include_files)
    task.set_outputs([bld.path.find_or_declare("generated/extension_headers.h")])
    bld.add_to_group(task)

    bld.set_group('compiling/c++')

    # Always build the C++ code
    intrinsics_bitcode_node = bld.path.find_or_declare(variant.inline_bitcode_archive_name("intrinsics"))
    builtins_bitcode_node = bld.path.find_or_declare(variant.inline_bitcode_archive_name("builtins"))
    fastgf_bitcode_node = bld.path.find_or_declare(variant.inline_bitcode_archive_name("fastgf"))
    cclasp_common_lisp_bitcode = bld.path.find_or_declare(variant.common_lisp_bitcode_name(bld.use_human_readable_bitcode,stage='c'))
    cxx_all_bitcode_node = bld.path.find_or_declare(variant.cxx_all_bitcode_name())
    out_dir_node = bld.path.find_dir(out)
    bclasp_symlink_node = out_dir_node.make_node("bclasp")
    bld_task = bld.program(source = clasp_c_source_files,
                           includes = include_dirs,
                           target = [bld.iclasp_executable],
                           install_path = '${PREFIX}/bin')

    #make_run_dsymutil_task(bld, 'i', iclasp_lto_o)

    if (bld.stage_val <= -1):
        log.info("Creating run_aclasp task")

        task = run_aclasp(env=bld.env)
        task.set_inputs([bld.iclasp_executable,
                         intrinsics_bitcode_node,
                         builtins_bitcode_node] +
                        waf_nodes_for_lisp_files(bld, bld.clasp_aclasp))
        aclasp_common_lisp_bitcode = bld.path.find_or_declare(variant.common_lisp_bitcode_name(bld.use_human_readable_bitcode, stage = 'a'))
        task.set_outputs(aclasp_common_lisp_bitcode)
        bld.add_to_group(task)
    if (bld.stage_val >= 1):
        log.info("Creating compile_aclasp task")

        task = compile_aclasp(env=bld.env)
        task.set_inputs([bld.iclasp_executable,
                         intrinsics_bitcode_node,
                         builtins_bitcode_node,
                         fastgf_bitcode_node] +
                        waf_nodes_for_lisp_files(bld, bld.clasp_aclasp))
        aclasp_common_lisp_bitcode = bld.path.find_or_declare(variant.common_lisp_bitcode_name(bld.use_human_readable_bitcode, stage = 'a'))
        log.debug("find_or_declare aclasp_common_lisp_bitcode = %s", aclasp_common_lisp_bitcode)
        task.set_outputs(aclasp_common_lisp_bitcode)
        bld.add_to_group(task)

        task = link_fasl(env=bld.env)
        task.set_inputs([fastgf_bitcode_node,
                         builtins_bitcode_node,
                         intrinsics_bitcode_node,
                         aclasp_common_lisp_bitcode])
        aclasp_link_product = bld.path.find_or_declare(variant.fasl_name(stage = 'a'))
        task.set_outputs([aclasp_link_product])
        bld.add_to_group(task)

        install('lib/clasp/', aclasp_link_product)
        install('lib/clasp/', aclasp_common_lisp_bitcode)
    if (bld.stage_val >= 2):
        log.info("Creating compile_bclasp task")

        task = compile_bclasp(env=bld.env)
        task.set_inputs([bld.iclasp_executable,
                         aclasp_link_product,
                         intrinsics_bitcode_node,
                         fastgf_bitcode_node,
                         builtins_bitcode_node] +
                        waf_nodes_for_lisp_files(bld, bld.clasp_bclasp))
        bclasp_common_lisp_bitcode = bld.path.find_or_declare(variant.common_lisp_bitcode_name(bld.use_human_readable_bitcode, stage = 'b'))
        task.set_outputs(bclasp_common_lisp_bitcode)
        bld.add_to_group(task)

        task = link_fasl(env=bld.env)
        task.set_inputs([fastgf_bitcode_node,
                         builtins_bitcode_node,
                         intrinsics_bitcode_node,
                         bclasp_common_lisp_bitcode])
        task.set_outputs([bld.bclasp_fasl])
        bld.add_to_group(task)

        install('lib/clasp/', bld.bclasp_fasl)
        install('lib/clasp/', bclasp_common_lisp_bitcode)

        if (False):   # build bclasp executable
            task = link_executable(env = bld.env)
            task.set_inputs([bclasp_common_lisp_bitcode,
                             cxx_all_bitcode_node])
            log.info("About to try and recurse into extensions again")
            bld.recurse('extensions')
            if ( bld.env['DEST_OS'] == DARWIN_OS ):
                if (bld.env.LTO_FLAG):
                    bclasp_lto_o = bld.path.find_or_declare('%s_exec.lto.o' % variant.executable_name(stage = 'b'))
                    task.set_outputs([bld.bclasp_executable,
                                      bclasp_lto_o])
                else:
                    bclasp_lto_o = None
                    task.set_outputs([bld.bclasp_executable])
            else:
                bclasp_lto_o = None
                task.set_outputs(bld.bclasp_executable)
            log.debug("link_executable for bclasp %s -> %s", task.inputs, task.outputs)
            bld.add_to_group(task)

            make_run_dsymutil_task(bld, 'b', bclasp_lto_o)

            install('bin/%s' % bld.bclasp_executable.name, bld.bclasp_executable, chmod = Utils.O755)
            bld.symlink_as('${PREFIX}/bin/clasp', bld.bclasp_executable.name)
            os.symlink(bld.bclasp_executable.abspath(), bclasp_symlink_node.abspath())
        # # Build ASDF for bclasp
        # cmp_asdf = compile_module(env = bld.env)
        # cmp_asdf.set_inputs([bld.iclasp_executable, bld.bclasp_fasl] + waf_nodes_for_lisp_files(bld, ["src/lisp/modules/asdf/build/asdf"]))
        # cmp_asdf.set_outputs(bld.asdf_fasl_bclasp)
        # bld.add_to_group(cmp_asdf)
        # install_files('lib/clasp/', bld.asdf_fasl_bclasp)
    if (bld.stage_val >= 3):
        log.info("Creating compile_cclasp task")
        # Build cclasp fasl
        task = compile_cclasp(env=bld.env)
        task.set_inputs([bld.iclasp_executable,
                         bld.bclasp_fasl,
                         cxx_all_bitcode_node] +
                        waf_nodes_for_lisp_files(bld, bld.clasp_cclasp))
        task.set_outputs([cclasp_common_lisp_bitcode])
        bld.add_to_group(task)
    if (bld.stage == 'rebuild' or bld.stage == 'dangerzone'):
        log.pprint('RED', "!------------------------------------------------------------")
        log.pprint('RED', "!   You have entered the dangerzone!  ")
        log.pprint('RED', "!   While you wait...  https://www.youtube.com/watch?v=kyAn3fSs8_A")
        log.pprint('RED', "!------------------------------------------------------------")
        # Build cclasp
        task = recompile_cclasp(env = bld.env)
        task.set_inputs(waf_nodes_for_lisp_files(bld, bld.clasp_cclasp_no_wrappers))
        task.set_outputs([cclasp_common_lisp_bitcode])
        bld.add_to_group(task)
    if (bld.stage == 'dangerzone' or bld.stage == 'rebuild' or bld.stage_val >= 3):
        task = link_fasl(env=bld.env)
        task.set_inputs([fastgf_bitcode_node,
                         builtins_bitcode_node,
                         intrinsics_bitcode_node,
                         cclasp_common_lisp_bitcode])
        task.set_outputs([bld.cclasp_fasl])
        bld.add_to_group(task)

        install('lib/clasp/', bld.cclasp_fasl)
    if (bld.stage == 'rebuild' or bld.stage_val >= 3):
        install('lib/clasp/', cclasp_common_lisp_bitcode)

        # Build serve-event
        serve_event_fasl = bld.path.find_or_declare("%s/src/lisp/modules/serve-event/serve-event.fasl" % variant.fasl_dir(stage = 'c'))
        task = compile_module(env=bld.env)
        task.set_inputs([bld.iclasp_executable,
                         bld.cclasp_fasl] +
                        waf_nodes_for_lisp_files(bld, ["src/lisp/modules/serve-event/serve-event"]))
        task.set_outputs(serve_event_fasl)
        bld.add_to_group(task)
        install('lib/clasp/', serve_event_fasl)

        # Build ASDF
        task = compile_module(env=bld.env)
        task.set_inputs([bld.iclasp_executable,
                         bld.cclasp_fasl] +
                        waf_nodes_for_lisp_files(bld, ["src/lisp/modules/asdf/build/asdf"]))
        task.set_outputs(bld.asdf_fasl_cclasp)
        bld.add_to_group(task)

        install('lib/clasp/', bld.asdf_fasl_cclasp)

        clasp_symlink_node = out_dir_node.make_node("clasp")
        log.debug("clasp_symlink_node =  %s", clasp_symlink_node)
        if (os.path.islink(clasp_symlink_node.abspath())):
            os.unlink(clasp_symlink_node.abspath())
    if (bld.stage == 'rebuild' or bld.stage_val >= 4):
        if (True):   # build cclasp executable
            task = link_executable(env = bld.env)
            task.set_inputs([cclasp_common_lisp_bitcode,
                             cxx_all_bitcode_node])
            log.info("About to try and recurse into extensions again")
            bld.recurse('extensions')
            if ( bld.env['DEST_OS'] == DARWIN_OS ):
                if (bld.env.LTO_FLAG):
                    cclasp_lto_o = bld.path.find_or_declare('%s_exec.lto.o' % variant.executable_name(stage = 'c'))
                    task.set_outputs([bld.cclasp_executable,
                                      cclasp_lto_o])
                else:
                    cclasp_lto_o = None
                    task.set_outputs([bld.cclasp_executable])
            else:
                cclasp_lto_o = None
                task.set_outputs(bld.cclasp_executable)
            log.debug("link_executable for cclasp %s -> %s", task.inputs, task.outputs)
            bld.add_to_group(task)

            make_run_dsymutil_task(bld, 'c', cclasp_lto_o)

            install('bin/%s' % bld.cclasp_executable.name, bld.cclasp_executable, chmod = Utils.O755)
            bld.symlink_as('${PREFIX}/bin/clasp', bld.cclasp_executable.name)
            os.symlink(bld.cclasp_executable.abspath(), clasp_symlink_node.abspath())
        else:
            os.symlink(bld.iclasp_executable.abspath(), clasp_symlink_node.abspath())
    log.pprint('BLUE', 'build() has finished')

def init(ctx):
    from waflib.Build import BuildContext, CleanContext, InstallContext, UninstallContext, ListContext, StepContext, EnvContext

    log.pprint('BLUE', "init()")

    for gc in GCS_NAMES:
        for debug_build in [True, False]:
            variant_name = gc + '_d' if debug_build else gc

            for ctx in (BuildContext, CleanContext, InstallContext, UninstallContext, ListContext, StepContext, EnvContext):
                name = ctx.__name__.replace('Context','').lower()
                for stage_char in STAGE_CHARS:
                    # This instantiates classes, all with the same name 'tmp'.
                    class tmp(ctx):
                        variant = variant_name
                        cmd = name + '_' + stage_char + variant_name
                        stage = stage_char

            # NOTE: these are kinda bitrotten, but left here for now as a reference
            class tmp(BuildContext):
                variant = variant_name
                cmd = 'rebuild_c' + variant
                stage = 'rebuild'
            class tmp(BuildContext):
                variant = variant_name
                cmd = 'dangerzone_c' + variant
                stage = 'dangerzone'

def buildall(ctx):
    for gc in GCS_NAMES:
        for debug_build in [True, False]:
            variant_name = gc + '_d' if debug_build else gc
            for stage_char in STAGE_CHARS:
                cmd = 'build_' + stage_char + variant_name
                waflib.Options.commands.insert(0, cmd)

#
#
# Tasks
#
#
def make_run_dsymutil_task(bld, stage_char, clasp_lto_o):
    if bld.env['DEST_OS'] == DARWIN_OS:
        variant = bld.variant_obj
        dsym_file = bld.path.find_or_declare("%s.dSYM" % variant.executable_name(stage = stage_char))
        dsym_nodes = dsym_waf_nodes(variant.executable_name(stage = stage_char), dsym_file)
        log.debug(stage_char + "clasp dsym_nodes = %s", dsym_nodes)
        task = run_dsymutil(env = bld.env)
        inputs = [bld.path.find_or_declare(variant.executable_name(stage = stage_char))]
        if clasp_lto_o:
            inputs += [clasp_lto_o]
        task.set_inputs(inputs)
        task.set_outputs(dsym_nodes)
        bld.add_to_group(task)
        bld.install_files('${PREFIX}/bin/%s' % dsym_file.name, dsym_nodes, relative_trick = True, cwd = dsym_file)

class run_dsymutil(clasp_task):
    color = 'BLUE';
    def run(self):
        cmd = 'dsymutil %s' % self.inputs[0]
        return self.exec_command(cmd)

class link_fasl(clasp_task):
    def run(self):
        if (self.env.LTO_FLAG):
            lto_option = self.env.LTO_FLAG
            if (self.env.USE_PARALLEL_BUILD and self.bld.stage_val < 3):
                lto_optimize_flag = "-O0"
                log.debug("With USE_PARALLEL_BUILD and stage_val = %d dropping down to -O0 for link_fasl", self.bld.stage_val)
            else:
                lto_optimize_flag = "-O2"
        else:
            lto_option = ""
            lto_optimize_flag = ""
        link_options = self.bld.env['LINKFLAGS']
        if (self.env['DEST_OS'] == DARWIN_OS):
            link_options = link_options + [ "-flat_namespace", "-undefined", "suppress", "-bundle" ]
        else:
            link_options = link_options + [ "-shared" ]
        cmd = [self.env.CXX[0]] + \
              waf_nodes_to_paths(self.inputs) + \
              [ lto_option, lto_optimize_flag ] + \
              link_options + \
              [ "-o", self.outputs[0].abspath() ]
        return self.exec_command(cmd)

class link_executable(clasp_task):
    def run(self):
        if (self.env.LTO_FLAG):
            lto_option_list = [self.env.LTO_FLAG,"-O2"]
            if (self.env['DEST_OS'] == DARWIN_OS ):
                lto_object_path_lto = ["-Wl,-object_path_lto,%s" % self.outputs[1].abspath()]
            else:
                lto_object_path_lto = []
        else:
            lto_option_list = []
            lto_object_path_lto = []
        link_options = []
        if (self.env['DEST_OS'] == DARWIN_OS ):
            link_options = link_options + [ "-flto=thin", "-v", '-Wl,-stack_size,0x1000000']
        cmd = [ self.env.CXX[0] ] + \
              waf_nodes_to_paths(self.inputs) + \
              self.env['LINKFLAGS'] + \
              self.env['LDFLAGS']  + \
              prefix_list_elements_with(self.env['LIBPATH'], '-L') + \
              prefix_list_elements_with(self.env['STLIBPATH'], '-L') + \
              libraries_as_link_flags(self.env.STLIB_ST,self.env.STLIB) + \
              libraries_as_link_flags(self.env.LIB_ST,self.env.LIB) + \
              lto_option_list + \
              link_options + \
              lto_object_path_lto + \
              [ "-o", self.outputs[0].abspath()]
        return self.exec_command(cmd)

class run_aclasp(clasp_task):
    def run(self):
        executable = self.inputs[0].abspath()
        log.debug("In run_aclasp %s", executable)
        cmd = self.clasp_command_line(executable,
                                      image = False,
                                      features = ["no-implicit-compilation",
                                                  "jit-log-symbols",
                                                  "clasp-min"],
                                      forms = ['(load "sys:kernel;clasp-builder.lsp")',
                                               '(load-aclasp)'],
                                      *self.bld.clasp_aclasp)
        return self.exec_command(cmd)

class compile_aclasp(clasp_task):
    def run(self):
        executable = self.inputs[0].abspath()
        output_file = self.outputs[0].abspath()
        log.debug("In compile_aclasp %s -> %s", executable, output_file)
        cmd = self.clasp_command_line(executable,
                                      image = False,
                                      features = ["clasp-min"],
                                      forms = ['(load "sys:kernel;clasp-builder.lsp")',
                                               #'(load-aclasp)',
                                               '(setq core::*number-of-jobs* %d)' % self.bld.jobs,
                                               '(core:compile-aclasp :output-file #P"%s")' % output_file,
                                               '(core:quit)'],
                                      *self.bld.clasp_aclasp)
        return self.exec_command(cmd)

class compile_bclasp(clasp_task):
    def run(self):
        executable = self.inputs[0].abspath()
        image_file = self.inputs[1].abspath()
        output_file = self.outputs[0].abspath()
        log.debug("In compile_bclasp %s %s -> %s", executable, image_file, output_file)
        cmd = self.clasp_command_line(executable,
                                      image = image_file,
                                      features = [],
                                      forms = ['(load "sys:kernel;clasp-builder.lsp")',
                                               '(setq core::*number-of-jobs* %d)' % self.bld.jobs,
                                               '(core:compile-bclasp :output-file #P"%s")' % output_file,
                                               '(core:quit)'],
                                      *self.bld.clasp_bclasp)

        return self.exec_command(cmd)

class compile_cclasp(clasp_task):
    def run(self):
        executable = self.inputs[0].abspath()
        image_file = self.inputs[1].abspath()
        output_file = self.outputs[0].abspath()
        log.debug("In compile_cclasp %s --image %s -> %s", executable, image_file, output_file)
        forms = ['(load "sys:kernel;clasp-builder.lsp")',
                 '(setq core::*number-of-jobs* %d)' % self.bld.jobs]
        if (self.bld.options.LOAD_CCLASP):
            forms += ['(load-cclasp)']
        else:
            forms += ['(core:compile-cclasp :output-file #P"%s")' % output_file,
                      '(core:quit)']
        cmd = self.clasp_command_line(executable,
                                      image = image_file,
                                      features = [],
                                      forms = forms,
                                      *self.bld.clasp_cclasp)
        return self.exec_command(cmd)

class recompile_cclasp(clasp_task):
    def run(self):
        env = self.env
        other_clasp = env.CLASP or "clasp"
        output_file = self.outputs[0]
        log.debug("In recompile_cclasp %s -> %s", other_clasp, output_file)
        if not os.path.isfile(other_clasp):
            raise Exception("To use the recompile targets you need to provide a working clasp executable. See wscript.config and/or set the CLASP env variable.")
        cmd = self.clasp_command_line(other_clasp,
                                      features = ['ignore-extensions'],
                                      resource_dir = os.path.join(self.bld.path.abspath(), out, self.bld.variant_obj.variant_dir()),
                                      forms = ['(load "sys:kernel;clasp-builder.lsp")',
                                               '(setq core::*number-of-jobs* %d)' % self.bld.jobs,
                                               '(core:recompile-cclasp :output-file #P"%s")' % output_file,
                                               '(core:quit)'],
                                      *self.bld.clasp_cclasp_no_wrappers)
        return self.exec_command(cmd)

class compile_module(clasp_task):
    def run(self):
        executable = self.inputs[0].abspath()
        image_file = self.inputs[1].abspath()
        source_file = self.inputs[2].abspath()
        fasl_file = self.outputs[0].abspath()
        log.debug("In compile_module %s --image %s, %s -> %s", executable, image_file, source_file, fasl_file)
        cmd = self.clasp_command_line(executable,
                                      image = image_file,
                                      features = ['ignore-extensions'],
                                      forms = ['(compile-file #P"%s" :output-file #P"%s" :output-type :fasl)' % (source_file, fasl_file),
                                               '(core:quit)'])
        return self.exec_command(cmd)

class generate_extension_headers_h(clasp_task):
    def run(self):
        log.debug("generate_extension_headers_h running, inputs: %s", self.inputs)
        output_file = self.outputs[0].abspath()
        new_contents = "// Generated by the wscript generate_extension_headers_h task - Editing it is unwise!\n"
        old_contents = ""
        for x in self.inputs[1:]:
            new_contents += ("#include \"%s\"\n" % x.abspath())
        if os.path.isfile(output_file):
            fin = open(output_file, "r")
            old_contents = fin.read()
            fin.close()
        if old_contents != new_contents:
            log.debug("Writing to %s", output_file)
            fout = open(output_file, "w")
            fout.write(new_contents)
            fout.close()
        else:
            log.debug("NOT writing to %s - it is unchanged", output_file)

class link_bitcode(clasp_task):
    ext_out = ['.a']    # this affects the task execution order

    def run(self):
        all_inputs = StringIO()
        for f in self.inputs:
            all_inputs.write(' %s' % f.abspath())
        cmd = "" + self.env.LLVM_AR_BINARY + " ru %s %s" % (self.outputs[0], all_inputs.getvalue())
        return self.exec_command(cmd)

class build_bitcode(clasp_task):
    ext_out = ['.sif']    # this affects the task execution order

    def run(self):
        env = self.env
        cmd = [] + \
              env.CXX + \
              self.colon("ARCH_ST", "ARCH") + \
              env.CXXFLAGS + env.CPPFLAGS + \
              [ '-emit-llvm' ] + \
              self.colon("FRAMEWORKPATH_ST", "FRAMEWORKPATH") + \
              self.colon("CPPPATH_ST", "INCPATHS") + \
              self.colon("DEFINES_ST", "DEFINES") + \
              [ self.inputs[0].abspath() ] + \
              [ '-c' ] + \
              [ '-o', self.outputs[0].abspath() ]
        cmd.remove("-g")
        return self.exec_command(cmd)

class scraper_task(clasp_task):
    def scraper_command_line(self, extraCommands = [], scraperArgs = []):
        env = self.env
        bld = self.generator.bld
        scraper_home = os.path.join(env.BUILD_ROOT, "src/scraper/")
        fasl_dir = os.path.join(bld.path.abspath(), out, "host-fasl/")
        cmd = [] + env.SCRAPER_LISP + [
            "--eval", "(require :asdf)",
            "--eval", "(asdf:initialize-source-registry '(:source-registry (:directory \"%s\") :ignore-inherited-configuration))" % scraper_home,
            "--eval", "(asdf:initialize-output-translations '(:output-translations (t (\"%s\" :implementation)) :inherit-configuration))" % fasl_dir,
            "--load", os.path.join(env.BUILD_ROOT, "src/scraper/dependencies/bundle.lisp"),
            "--eval", "(let ((uiop:*uninteresting-conditions* (list* 'style-warning uiop:*usual-uninteresting-conditions*)) (*compile-print* nil) (*compile-verbose* nil)) (asdf:load-system :clasp-scraper))",
            ] + extraCommands + [
            "--eval", "(quit)", "--end-toplevel-options"] + scraperArgs
        return cmd

class precompile_scraper(scraper_task):
    weight = 5    # Tell waf to run this early among the equal tasks because it will take long
    before = ['expand_pump_template']

    def run(self):
        cmd = self.scraper_command_line(["--eval", '(with-open-file (stream "%s" :direction :output :if-exists :supersede) (terpri stream))' % self.outputs[0].abspath()])
        return self.exec_command(cmd)

class generate_sif_files(scraper_task):
    ext_out = ['.sif']    # this affects the task execution order
    after = ['expand_pump_template']
    waf_print_keyword = "Scraping"

    def run(self):
        env = self.env
        preproc_args = [] + env.CXX + ["-E", "-DSCRAPING"] + self.colon("ARCH_ST", "ARCH") + env.CXXFLAGS + env.CPPFLAGS + \
                       self.colon("FRAMEWORKPATH_ST", "FRAMEWORKPATH") + \
                       self.colon("CPPPATH_ST", "INCPATHS") + \
                       self.colon("DEFINES_ST", "DEFINES")
        preproc_args_as_string = ' '.join('"' + item + '"' for item in preproc_args)
        cmd = self.scraper_command_line(["--eval", "(cscrape:generate-sif-files '(%s))" % preproc_args_as_string])
        for cxx_node, sif_node in zip(self.inputs, self.outputs):
            cmd.append(cxx_node.abspath())
            cmd.append(sif_node.abspath())

        return self.exec_command(cmd)

class generate_headers_from_all_sifs(scraper_task):
    waf_print_keyword = "Scraping, generate-headers-from-all-sifs"

    def run(self):
        env = self.env
        bld = self.generator.bld
        cmd = self.scraper_command_line(["--eval", "(cscrape:generate-headers-from-all-sifs)"],
                                        [os.path.join(bld.path.abspath(), out, bld.variant_obj.variant_dir() + "/"),
                                         env.BUILD_ROOT + "/"])
        for f in self.inputs:
            cmd.append(f.abspath())
        return self.exec_command(cmd)

def make_pump_tasks(bld, template_dir, output_dir):
    log.debug("Building pump tasks: %s -> %s", template_dir, output_dir)
    templates = collect_waf_nodes(bld, template_dir, suffix = '.pmp')
    assert len(templates) > 0
    for template_node in templates:
        template_name = template_node.name
        output_path = os.path.join("generated/", output_dir, template_name.replace(".pmp", ".h"))
        output_node = bld.path.find_or_declare(output_path)
        log.debug("Creating expand_pump_template: %s -> %s", template_node.abspath(), output_node.abspath())
        assert output_node
        task = expand_pump_template(env = bld.env)
        task.set_inputs([template_node])
        task.set_outputs([output_node])
        bld.add_to_group(task)
        bld.install_files('${PREFIX}/lib/clasp/', [output_node], relative_trick = True, cwd = bld.path)
    log.info("Created %s pump template tasks found in dir: %s", len(templates), template_dir)

class expand_pump_template(clasp_task):
    ext_out  = ['.h']      # this affects the task execution order

    def run(self):
        assert len(self.inputs) == len(self.outputs) == 1
        cmd = ['python',
               os.path.join(self.bld.path.abspath(), "tools-for-build/pump.py"),
               self.inputs[0].abspath(),
               self.outputs[0].abspath()]
        return self.exec_command(cmd)

#
#
# TaskGen's
#
#
@TaskGen.feature('cxx')
@TaskGen.after('process_source')
def postprocess_all_c_tasks(self):

    def install(dest, files, cwd = self.bld.path):
        dest = '${PREFIX}/' + dest
        self.bld.install_files(dest, files, relative_trick = True, cwd = cwd)

    if (not 'variant_obj' in self.bld.__dict__):
        log.debug("It's not the main build, bailing out from postprocess_all_c_tasks")
        return

    if (not self.bld.options.RUN_THE_SCRAPER):
        log.warn("Skipping scrape and some C tasks as requested")
        return

    variant = self.bld.variant_obj
    all_o_nodes = []
    all_cxx_nodes = []
    intrinsics_o = None
    builtins_o = None
    fastgf_o = None
    for task in self.compiled_tasks:
        log.debug("Scrape taskgen inspecting C task %s", task)
        if ( task.__class__.__name__ == 'cxx' ):
            for node in task.inputs:
                all_cxx_nodes.append(node)
                if ends_with(node.name, 'intrinsics.cc'):
                    intrinsics_cc = node
                if ends_with(node.name, 'builtins.cc'):
                    builtins_cc = node
                if ends_with(node.name, 'fastgf.cc'):
                    fastgf_cc = node
            for node in task.outputs:
                all_o_nodes.append(node)
                if ends_with(node.name, 'intrinsics.cc'):
                    intrinsics_o = node
                if ends_with(node.name, 'builtins.cc'):
                    builtins_o = node
                if ends_with(node.name, 'fastgf.cc'):
                    fastgf_o = node
        if ( task.__class__.__name__ == 'c' ):
            for node in task.outputs:
                all_o_nodes.append(node)

    all_sif_nodes = []

    # Start 'jobs' number of scraper processes in parallel, each processing several files
    #chunks = split_list(all_cxx_nodes, min(self.bld.jobs, len(all_cxx_nodes))) # this splits into the optimal chunk sizes
    chunk_size = min(20, max(1, len(all_cxx_nodes) // self.bld.jobs)) # this splits into task chunks of at most 20 files
    chunks = list(list_chunks_of_size(all_cxx_nodes, chunk_size))
    log.info('Creating %s parallel scraper tasks, each processing %s files, for the total %s cxx files', len(chunks), chunk_size, len(all_cxx_nodes))
    assert len([x for sublist in chunks for x in sublist]) == len(all_cxx_nodes)
    for cxx_nodes in chunks:
        sif_nodes = [x.change_ext('.sif') for x in cxx_nodes]
        all_sif_nodes += sif_nodes
        self.create_task('generate_sif_files', cxx_nodes, sif_nodes)

    scraper_output_nodes = [self.path.find_or_declare('generated/' + i) for i in
                            ['c-wrappers.h',
                             'cl-wrappers.lisp',
                             'enum_inc.h',
                             'initClassesAndMethods_inc.h',
                             'initFunctions_inc.h',
                             'initializers_inc.h',
                             'sourceInfo_inc.h',
                             'symbols_scraped_inc.h']]

    self.create_task('generate_headers_from_all_sifs', all_sif_nodes, scraper_output_nodes)
    # TODO FIXME this includes cl-wrappers.lisp
    install('lib/clasp/', scraper_output_nodes)  # includes

# intrinsics
    intrinsics_bitcode_archive_node = self.path.find_or_declare(variant.inline_bitcode_archive_name("intrinsics"))
    intrinsics_bitcode_alone_node = self.path.find_or_declare(variant.inline_bitcode_name("intrinsics"))
    log.debug("intrinsics_cc = %s, intrinsics_o.name = %s, intrinsics_bitcode_alone_node = %s", intrinsics_cc, intrinsics_o.name, intrinsics_bitcode_alone_node)
    self.create_task('build_bitcode',
                     [intrinsics_cc] + scraper_output_nodes,
                     intrinsics_bitcode_alone_node)
    self.create_task('link_bitcode',
                     [intrinsics_o],
                     intrinsics_bitcode_archive_node)
    install('lib/clasp/', intrinsics_bitcode_archive_node)   # install bitcode
    install('lib/clasp/', intrinsics_bitcode_alone_node)     # install bitcode

# builtins
    builtins_bitcode_archive_node = self.path.find_or_declare(variant.inline_bitcode_archive_name("builtins"))
    builtins_bitcode_alone_node = self.path.find_or_declare(variant.inline_bitcode_name("builtins"))
    log.debug("builtins_cc = %s, builtins_o.name = %s, builtins_bitcode_alone_node = %s", builtins_cc, builtins_o.name, builtins_bitcode_alone_node)
    self.create_task('build_bitcode',
                     [builtins_cc] + scraper_output_nodes,
                     builtins_bitcode_alone_node)
    self.create_task('link_bitcode',
                     [builtins_o],
                     builtins_bitcode_archive_node)
    install('lib/clasp/', builtins_bitcode_archive_node)
    install('lib/clasp/', builtins_bitcode_alone_node)

# fastgf
    fastgf_bitcode_archive_node = self.path.find_or_declare(variant.inline_bitcode_archive_name("fastgf"))
    fastgf_bitcode_alone_node = self.path.find_or_declare(variant.inline_bitcode_name("fastgf"))
    log.debug("fastgf_cc = %s, fastgf_o.name = %s, fastgf_bitcode_alone_node = %s", fastgf_cc, fastgf_o.name, fastgf_bitcode_alone_node)
    self.create_task('build_bitcode',
                     [fastgf_cc] + scraper_output_nodes,
                     fastgf_bitcode_alone_node)
    self.create_task('link_bitcode',
                     [fastgf_o],
                     fastgf_bitcode_archive_node)
    install('lib/clasp/', fastgf_bitcode_archive_node)
    install('lib/clasp/', fastgf_bitcode_alone_node)

# all of C
    cxx_all_bitcode_node = self.path.find_or_declare(variant.cxx_all_bitcode_name())
    self.create_task('link_bitcode',
                     all_o_nodes,
                     cxx_all_bitcode_node)
    install('lib/clasp/', cxx_all_bitcode_node)
