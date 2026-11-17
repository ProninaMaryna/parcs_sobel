#!/usr/bin/env bash
# PARCS-Python on AWS EC2: master + worker1..worker4.
# Run in AWS CloudShell (the region selected in the console is used).
#
#   MY_IP=1.2.3.4 bash aws_setup.sh
#   TYPE=t3.small MY_IP=1.2.3.4 bash aws_setup.sh     # another instance type
set -euo pipefail

MY_IP="${MY_IP:?set MY_IP to your public IPv4 (web UI access)}"
TYPE="${TYPE:-t3.micro}"            # free-tier eligible, 2 vCPU / 1 GB
REGION="${AWS_REGION:-$(aws configure get region)}"
TAG=parcs
echo ">>> region: $REGION, instance type: $TYPE"

# Amazon Linux 2023, latest x86_64 image
AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
      --query Parameter.Value --output text)

# default VPC (create it if the account has none) + one subnet, so all nodes are in one AZ
VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
if [ "$VPC" = "None" ]; then
  VPC=$(aws ec2 create-default-vpc --query Vpc.VpcId --output text)
fi
SUBNET=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC" Name=default-for-az,Values=true \
         --query 'sort_by(Subnets,&AvailabilityZone)[0].SubnetId' --output text)
echo ">>> VPC $VPC, subnet $SUBNET"

# security group: web UI 8080 only from my IP; nodes talk to each other freely (Pyro4 uses random ports)
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=parcs-sg Name=vpc-id,Values="$VPC" \
     --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name parcs-sg --description "PARCS cluster" \
       --vpc-id "$VPC" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --group-id "$SG" \
      --protocol tcp --port 8080 --cidr "$MY_IP/32" >/dev/null
  aws ec2 authorize-security-group-ingress --group-id "$SG" \
      --protocol -1 --source-group "$SG" >/dev/null
fi
echo ">>> security group $SG"

user_data () {  # $1 = PARCS_ARGS
cat <<EOF
#!/bin/bash
# 1 GB RAM is tight for a 2000x2000 image in Python 2 -> add 2 GB swap
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
dnf install -y docker
systemctl enable --now docker
docker run -d --restart=always --net=host -e PARCS_ARGS="$1" hummer12007/parcs-node
EOF
}

launch () {  # $1 = Name tag, $2 = user-data file  -> prints instance id
  aws ec2 run-instances --image-id "$AMI" --instance-type "$TYPE" --count 1 \
    --network-interfaces "DeviceIndex=0,SubnetId=$SUBNET,Groups=$SG,AssociatePublicIpAddress=true" \
    --credit-specification CpuCredits=unlimited \
    --user-data "file://$2" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$1},{Key=project,Value=$TAG}]" \
    --query 'Instances[0].InstanceId' --output text
}

user_data master > /tmp/ud_master.sh
MASTER_ID=$(launch master /tmp/ud_master.sh)
MASTER_IP=$(aws ec2 describe-instances --instance-ids "$MASTER_ID" \
             --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)
echo ">>> master $MASTER_ID, private IP $MASTER_IP"

user_data "worker $MASTER_IP" > /tmp/ud_worker.sh
IDS=("$MASTER_ID")
for i in 1 2 3 4; do
  IDS+=("$(launch "worker$i" /tmp/ud_worker.sh)")
  echo ">>> worker$i ${IDS[-1]}"
done

echo ">>> waiting for all instances to be running ..."
aws ec2 wait instance-running --instance-ids "${IDS[@]}"

aws ec2 describe-instances --filters Name=tag:project,Values=$TAG Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].{Name:Tags[?Key==`Name`]|[0].Value, Type:InstanceType, PrivateIp:PrivateIpAddress, PublicIp:PublicIpAddress, State:State.Name}' \
  --output table

MASTER_PUB=$(aws ec2 describe-instances --instance-ids "$MASTER_ID" \
             --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo
echo "PARCS UI: http://$MASTER_PUB:8080   (ready in ~2-3 min, after Docker pulls the image)"
