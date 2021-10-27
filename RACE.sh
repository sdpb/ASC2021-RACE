#!/bin/bash

#
# Open the link below before executing this script
# https://www.youtube.com/watch?v=dQw4w9WgXcQ
# ;)
# This script requires pipenv in order to work better
#

function banner() {
    RED='\033[0;31m'
    YELLOW='\033[0;33m'
    CYAN='\033[0;36m'
    NC='\033[0m'
    TEXT=$CYAN
    BORDER=$YELLOW
    EDGE=$(echo "  $1  " | sed 's/./~/g')

    if [ "$2" == "warn" ]; then
        TEXT=$YELLOW
        BORDER=$RED
    fi

    MSG="${BORDER}~ ${TEXT}$1 ${BORDER}~${NC}"
    echo -e "${BORDER}$EDGE${NC}"
    echo -e "$MSG"
    echo -e "${BORDER}$EDGE${NC}"
}


banner "Checking update for IA repo"
git pull

banner "Installing dependencies"
pipenv install || exit 1

banner "Installing PyTorch"
pipenv run pip install torch==1.10.0+cu113 torchvision==0.11.1+cu113 torchaudio==0.10.0+cu113 -f https://download.pytorch.org/whl/cu113/torch_stable.html || exit 1

sudo yum install -y libaio-devel python3-devel
banner "Installing DeepSpeed"
DS_BUILD_OPS=1 pipenv run pip install --no-cache-dir deepspeed || exit 1

banner "Git clone apex"
if [ ! -d apex ]; then
	git clone https://github.com/NVIDIA/apex.git
fi

pipenv run python -c "from apex import amp" > /dev/null >&1

APEX_INSTALLED=$?

cd apex || exit 1

git pull | grep -i "up to date" > /dev/null 2>&1


banner "Modifying setup.py in the apex dir" warn
echo 's/check_cuda_torch_binary_vs_bare_metal(CUDA_HOME)/# check_cuda_torch_binary_vs_bare_metal(CUDA_HOME)/g'

sed -i 's/check_cuda_torch_binary_vs_bare_metal(CUDA_HOME)/# check_cuda_torch_binary_vs_bare_metal(CUDA_HOME)/g' setup.py

APEX_UPDATED=$?

if [ $APEX_INSTALLED -eq 1 ] || [ $APEX_UPDATED -eq 1 ]; then
	banner "Update apex"
	pipenv run pip install -q --disable-pip-version-check --no-cache-dir --global-option="--cpp_ext" --global-option="--cuda_ext" ./ || exit 1

else
	banner "APEX seems to be up to date"
fi


cd ../ || exit 1

#banner "Run training"
#./run.sh || exit 1

#banner "Run eval"
#./eval.sh || exit 1
