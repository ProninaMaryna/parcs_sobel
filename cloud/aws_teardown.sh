#!/usr/bin/env bash
# Terminate every instance tagged project=parcs and delete the parcs-sg security group.
#   bash aws_teardown.sh
set -uo pipefail

IDS=$(aws ec2 describe-instances --filters Name=tag:project,Values=parcs \
      Name=instance-state-name,Values=pending,running,stopping,stopped \
      --query 'Reservations[].Instances[].InstanceId' --output text)
if [ -n "$IDS" ]; then
  echo ">>> terminating: $IDS"
  aws ec2 terminate-instances --instance-ids $IDS --output table --query 'TerminatingInstances[].[InstanceId,CurrentState.Name]'
  aws ec2 wait instance-terminated --instance-ids $IDS
fi

SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=parcs-sg \
     --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" != "None" ]; then
  for try in 1 2 3 4 5 6; do   # network interfaces may need a few seconds to detach
    aws ec2 delete-security-group --group-id "$SG" 2>/dev/null && { echo ">>> deleted security group $SG"; break; }
    sleep 10
  done
fi

echo ">>> left with tag project=parcs:"
aws ec2 describe-instances --filters Name=tag:project,Values=parcs \
  --query 'Reservations[].Instances[].[Tags[?Key==`Name`]|[0].Value,State.Name]' --output table
