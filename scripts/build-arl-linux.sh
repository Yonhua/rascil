#!/bin/bash

# =========================================================== #
# Set of comands to Install rascil and wrapper into Linux system #
# =========================================================== #

# Load the dependency modules
# PYTHON 3.6 +
# GIT 2.10+
# GIT-LFS 
# i.e.:
#module load python-3.5.2-gcc-5.4.0-rdp6q5l
#module load python-3.6.1-gcc-5.4.0-23fr5u4
#module load git-2.14.1-gcc-5.4.0-acb553e
#module load git-lfs-2.3.0-gcc-5.4.0-oktvmkw
#module load cfitsio-3.410-gcc-5.4.0-tp3pkyv


# ########################################################### #
# If repository is cloned skip this part ....                 #
# Clone the repository
#git clone https://github.com/SKA-ScienceDataProcessor/rascil/
#cd rascil/

# Get the data
#git-lfs pull
# ########################################################### #


# ########################################################### #
# This should be executed from RASCIL                        #
# i.e. source scripts/build-rascil-linux.sh                      #
# ########################################################### #

# Start the building ARL through building a python virtualenvironment
virtualenv -p `which python3` _build
source _build/bin/activate
pip install --upgrade pip
pip install -U setuptools
pip install coverage numpy
pip install -r requirements.txt 
pip install virtualenvwrapper

echo 'Adding the rascil and ffiwrappers path to the virtual environment'
echo '(equivalent to setting up PYTHONPATH environment variable)'
# this updates _build/lib/python3.x/site-packages/_virtualenv_path_extensions.pth
source virtualenvwrapper.sh
add2virtualenv $PWD
add2virtualenv $PWD/ffiwrappers/src/

# This is required for some systems (i.e. Jenkins server or macos) others
# detect the python libraries alone and link with correct flags without setting up
# the flags explicitely
export LDFLAGS="$(python3-config --ldflags) -lcfitsio"
python setup.py install

# Test the ffiwrappers
export RASCIL=$PWD
source tests/ffiwrapped/run-tests.sh

#ldd libarlffi.so 
#cd timg_serial/
#make run

