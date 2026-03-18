# Ansible runner image for netops-stack orchestrator (from LTROPS-2341 pattern).
# requirements.txt must include paramiko (SSH/network_cli for collect_configs, compare_configs).
# Build: docker build -f gitlab/Dockerfile gitlab/ -t 198.18.134.23:5050/netops-stack/network-automation:latest
# Push: docker push 198.18.134.23:5050/netops-stack/network-automation:latest
#
# Source: https://github.com/tspuhler/LTROPS-2341 (docker/Dockerfile)

# Pinned multi-arch index digest (docker buildx imagetools inspect ubuntu:24.04)
FROM ubuntu:24.04@sha256:0d39fcc8335d6d74d5502f6df2d30119ff4790ebbb60b364818d5112d9e3e932

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    python3 \
    python3-pip \
    ssh-client \
    sshpass \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements.yml ./

RUN python3 -m pip config set global.break-system-packages true && \
    pip3 install --no-cache-dir -r requirements.txt && \
    ansible-galaxy collection install -r requirements.yml
