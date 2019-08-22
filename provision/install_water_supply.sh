#!/usr/bin/env bash

# Expect NISMOD dir as first argument
base_path=$1

# Read remote_data, local_dir from config.ini
eval "$(grep -A4 "\[water-supply\]" $base_path/provision/config.ini | tail -n4)"

# Locations for the git repo (temporary) and the nodal-related files
repo_dir=$local_dir/repo
nodal_dir=$local_dir/nodal
exe_dir=$local_dir/exe
dim_dir=$dim_dir

# Clone repo and copy necessary files to the model directory
mkdir -p $repo_dir
git clone git@github.com:nismod/water_supply.git $repo_dir || exit "$?"
pushd $repo_dir
    git checkout $model_version
popd

mkdir -p $exe_dir
cp $repo_dir/wathnet/w5_console.exe $exe_dir
cp $repo_dir/models/National_Model.wat $exe_dir

# Seems to be necessary to add execution to the wathnet exe
chmod +x $exe_dir/w5_console.exe

# Copy files needed for creating nodal file. This will be superseded by data being fed directly.
mkdir -p $nodal_dir
cp $local_dir/repo/scripts/preprocessing/prepare_nodal.py $nodal_dir

# Copy data dimensions
mkdir -p $dim_dir
cp $repo_dir/data_dimensions/* $dim_dir

# Clean up the cloned repo
rm -rf $repo_dir
