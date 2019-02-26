#!/bin/bash -l
#SBATCH -q debug
#SBATCH -N 1
#SBATCH -t 00:30:00
#SBATCH -J izhi
#SBATCH -L SCRATCH,project
#SBATCH -C haswell
#SBATCH --mail-user vbaratham@berkeley.edu
#SBATCH --mail-type BEGIN,END,FAIL
#SBATCH --output "/global/cscratch1/sd/vbaratha/izhi/runs/slurm/%j.out"
#SBATCH --error "/global/cscratch1/sd/vbaratha/izhi/runs/slurm/%j.err"

cd /global/cscratch1/sd/vbaratha/izhi

RUNDIR=runs/${SLURM_JOB_ID}
mkdir $RUNDIR


declare -a arr=("ramp" "step" "noise")

for stim_type in "${arr[@]}"
do
    for i in {00..07}
    do
        OUTFILE=$RUNDIR/izhi_${stim_type}_${i}.h5
        
        ## Report the stim type/idx
        echo "STIM" $stim_type $i
        echo "OUTFILE" $OUTFILE

        args="--outfile $OUTFILE --stim-type $stim_type --stim-idx $i"
        
        ## Create the output file
        srun -n 1 python run.py $args --create

        ## Run the simulation
        srun --label -n 64 python run.py $args --param-sweep
    done
done

# stim_type='step'
# i=7
# srun --label -n 64 python run.py \
#      --outfile $OUTFILE --stim-type $stim_type --stim-idx $i --param-sweep

