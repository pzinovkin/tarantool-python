import os.path

from setuptools import setup

# Hack to prevent stupid "TypeError: 'NoneType' object is not callable" error
# in multiprocessing/util.py _exit_function when running `python
# setup.py test` (see
# http://www.eby-sarna.com/pipermail/peak/2010-May/003357.html)
try:
    import multiprocessing  # noqa
except ImportError:
    pass


from tarantool import __version__


# Extra commands for documentation management
cmdclass = {}
command_options = {}

# Build Sphinx documentation (html)
# python setup.py build_sphinx
# generates files into build/sphinx/html
try:
    from sphinx.setup_command import BuildDoc
    cmdclass['build_sphinx'] = BuildDoc
except ImportError:
    pass


# Upload Sphinx documentation to PyPI (using Sphinx-PyPI-upload)
# python setup.py build_sphinx
# updates documentation at http://packages.python.org/tarantool/
try:
    from sphinx_pypi_upload import UploadDoc
    cmdclass['upload_sphinx'] = UploadDoc
    command_options['upload_sphinx'] = {
        'upload_dir': (
            'setup.py',
            os.path.join(os.path.dirname(__file__), 'build', 'sphinx', 'html')
        )
    }
except ImportError:
    pass


setup(
    name='mailru-tarantool',
    packages=['tarantool'],
    version=__version__,
    tests_require=[
        'nose==1.2.1',
    ],
    test_suite='nose.collector',
    platforms=['all'],
    author='Konstantin Cherkasoff',
    author_email='k.cherkasoff@gmail.com',
    url='https://github.com/coxx/tarantool-python',
    license='BSD',
    description='Python client library for Tarantool Database',
    long_description=open('README.rst').read(),
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Database :: Front-Ends'
    ],
    cmdclass=cmdclass,
    command_options=command_options
)
