#!/bin/bash

YEAR=$(date +"%Y")
REGEX="(Copyright\(c\) )([0-9]{4}-([0-9]{4}))( Intel Corporation)"
FILE=$(cat $1)
if [[  $FILE =~ $REGEX ]]
then
    if [[ $YEAR == ${BASH_REMATCH[3]} ]]
    then
        echo $1 have appropriate licence
    else
        echo $1 does not contain appropriate licence header && exit 1
    fi
    
fi
REGEX="^(Copyright\(c\) )([0-9]{4})( Intel Corportation)"
if [[  $FILE =~ $REGEX ]]
then
    if [[ $YEAR == ${BASH_REMATCH[2]} ]]
    then
        echo $1 have appropriate licence
    else
        echo $1 does not contain appropriate licence header && exit 1
    fi
    
fi