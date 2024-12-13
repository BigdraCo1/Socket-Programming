#!/bin/bash

if [ $# -eq 0 ]; then
    echo "Usage: $0 <argument>"
    exit 1
fi

dir="${1%/*}/"        
pattern="${1##*/}"    
pattern="${pattern%%.*}" 

gcc $1 -o $dir$pattern

./$dir$pattern
