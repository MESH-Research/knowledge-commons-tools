# MESH Research Tools

![Python](https://img.shields.io/badge/python-v3.12+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](http://makeapullrequest.com)
![Last Commit](https://img.shields.io/github/last-commit/MESH-Research/knowledge-commons-tools)


**This project is a work in progress and not complete.** 

This project provides tools for working with MESH Research Knowledge Commons systems.

## get_ip.py

    Usage: get_ip.py [OPTIONS] CLUSTER_NAME
    
      Get IP addresses of EC2 instances running ECS services.
    
      CLUSTER_NAME: Name of the ECS cluster
    
    Options:
      -s, --service TEXT    Specific service name (optional)
      -r, --region TEXT     AWS region name
      -p, --profile TEXT    AWS profile name
      --private / --public  Use private IPs instead of public
      --help                Show this message and exit.


## Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

## License
This project is licensed under the MIT License - see the LICENSE file for details.

