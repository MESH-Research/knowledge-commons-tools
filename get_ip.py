import click

from ecs_utils import get_cluster_service_ips


@click.command()
@click.argument("cluster_name")
@click.option("--service", "-s", help="Specific service name (optional)")
@click.option("--region", "-r", help="AWS region name", default="us-east-1")
@click.option("--profile", "-p", help="AWS profile name", default=None)
@click.option(
    "--private/--public",
    default=True,
    help="Use private IPs instead of public",
)
def get_ecs_service_ips(cluster_name, service, region, profile, private):
    """Get IP addresses of EC2 instances running ECS services.

    CLUSTER_NAME: Name of the ECS cluster
    """
    try:
        result = get_cluster_service_ips(
            region, profile, cluster_name, service, private
        )
    except Exception as e:
        click.echo(f"Unexpected error: {str(e)}", err=True)
        raise click.Abort()

    if not result:
        click.echo("No EC2 instances found running services", err=True)
        return

    for (cluster, service_name), ips in sorted(result.items()):
        click.echo(f"\nService: {service_name}")
        for ip in ips:
            click.echo(f"  {ip}")


if __name__ == "__main__":
    get_ecs_service_ips()
