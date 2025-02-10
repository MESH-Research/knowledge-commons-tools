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

## get_all_ips.py

    Usage: get_all_ips.py [OPTIONS]

    Get IP addresses of all EC2 instances in all clusters.

## Environment Variables

The following environment variables are required to run get_ip or get_all_ips:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

## Bash/ZSH Aliases for Convenient Use

You can add some aliases to your `.zshrc` or `.bashrc` file to make using the tool convenient.

If you install the tool using uv in a project environment, you can add the following aliases to run the script from any command line location:

```bash
alias get_kc_ip="uv run --project /Path/to/my/project/knowledge-commons-tools /Path/to/my/project/knowledge-commons-tools/get_ip.py"
alias get_kc_ips="uv run --project /Path/to/my/project/knowledge-commons-tools /Path/to/my/project/knowledge-commons-tools/get_all_ips.py"
```

Then you can add further aliases to integrate the tool into your SSH calls. To connect with the `kcworks-dev` cluster, you could add the following alias:

```bash
alias ssh_dev="ssh -i '~/.ssh/my-key.pem' ec2-user@$(get_kc_ip kcworks-dev | grep -oE '[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}')"
```

This assumes that you have the required SSH key in a file at `~/.ssh/my-key.pem`.

## Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

## License
This project is licensed under the MIT License - see the LICENSE file for details.

