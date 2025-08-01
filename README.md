# Usefull kubernetes Operators

https://github.com/patroni/patroni

https://github.com/CrunchyData/postgres-operator

Traefik for managing ingress:

https://github.com/traefik/traefik

# Good parctices

- Always add one separate server for backups
- Always allocate one server for a logical or physical replica
- for automated failover, allocate the following: An additional node to act as a voter , or a fully qualified replica
- if non local data acess latency allocate the following : an additinal rep lica in the primary location , an additional replica in each location for symmetric clusters
- For replication, use asynchronous replication wiyh streaming replication
- While there are a few logical asynchronous replication systems for PostgreSQL,
  Slony-I (Slony, in short) was the first to gain wide adoption.
      Good tool for High Availability:

      - repmgr is a replication management tool

      ![image.png](https://prod-files-secure.s3.us-west-2.amazonaws.com/591e41a4-136e-4570-8677-01dd5a14ebcf/21bf76d2-ba6c-458c-8708-984f0f53992b/image.png)

fully automated high availability stack using
the repmgr replica and cluster-management tools by 2ndQuadrant

- reparing systems for repmgr
- Installing and configuring repmgr
- Cloning a database with repmgr
  Incorporating a repmgr witness
  Performing a managed failover
  Customizing the failover process
  Using an outage to test availability
  Returning a node to the cluster
  Integrating primary fencing
  Performing online maintenance and upgrades

## minimum professional design

Two PostgreSQL servers and backup system.
Minimum three nodes with a primary a standby an d a backup

![image.png](https://prod-files-secure.s3.us-west-2.amazonaws.com/591e41a4-136e-4570-8677-01dd5a14ebcf/71b0c432-0119-475c-a2f4-9c9ff78d9ecc/image.png)

## More robust solution

One Primary PostgreSQL server, two replicas per node/pod/vps , a witness node and a backup server so eight nodes dedicated to PostgreSQL

![image.png](https://prod-files-secure.s3.us-west-2.amazonaws.com/591e41a4-136e-4570-8677-01dd5a14ebcf/5d380093-3629-428f-92aa-70f4d5ebcf1f/image.png)

## Considerations

- If automated failover is desirable, consider at least three data centers.
- Keep at least three copies of your datas
- two copies on different devices, one offsite
- At least one copy must be a replica
- The most common way to guarantee a quorum for a PostgreSQL
  cluster is by utilizing a witness node
- we must satisfy the capability for avoiding tie votes
- Basically, this means we must have an odd number of PostgreSQL nodes within our cluster such that there's always a majority.

How to apply these considerations:

1. If the initial PostgreSQL node count is even, add one witness node.
2. If the initial PostgreSQL node count is odd, convert one replica into a
   witness node.
3. In the presence of two locations, the witness node should reside in the same
   data center as the primary node.
4. If possible, allocate witness nodes in an independent tertiary location.

Hardware load balancers are utilized to redirect →

Connection multiplexing software such as PgBouncer or HAProxy

Preventing split brain → very bad can cause data corruption

As the usage volume of the cluster increases, we will inevitably require further nodes. A popular method of addressing this is to regionalize the primary nodes, but otherwise follow standard replication concepts.

# Configuration

Find these settings in the postgresql.conf file for the desired PostgreSQL instance,
and then perform the following steps:

1. Set max_connections to three times the number of processor cores on the
   server. Include virtual (hyperthreading) cores.
2. Set shared_buffers to 25 percent of RAM for servers with up to 32 GB of
   RAM. For larger servers, start with 8GB and then test for higher values in
   increments of 2 GB.
3. Set work_mem to 8MB for servers with up to 32 GB of RAM, 16MB for servers
   with up to 64 GB of RAM, and 32MB for systems with more than 64 GB of
   RAM. If max_connections is greater than 400, divide this by 2.
4. Set maintenance_work_mem to 1GB.
5. Set wal_level to one of these settings:
   Use hot_standby for versions prior to 9.4.
   Use logical for versions 9.4 and higher.
6. Set hot_standby to on.
7. Set the minimum write-ahead logging (WAL) size to 10 percent of system
   RAM:
   Divide this value by 16 and use the checkpoint_segments
   parameter for 9.4 and below.
   Use min_wal_size for 9.5 and beyond. Then, double this value and
   use it to set max_wal_size.
8. Set vacuum_cost_limit to 2000.
9. Set checkpoint_completion_target to 0.9.
10. Set archive_mode to on.
11. Set archive_command to /bin/true.
12. Set max_wal_senders to 10.
13. Retain the necessary WAL files with these settings:
14. Set wal_keep_segments to 3 \* checkpoint_segments for 9.3 and below.
    Set replication_slots to 10 for 9.4 and higher.
15. Set random_page_cost to 2.0 if you are using RAID or highperformance
    storage area network (SAN); 1.1 for SSD-based storage.
16. Set effective_cache_size to 75 percent of the available system RAM.
17. Set log_min_duration_statement to 1000.
18. Set log_checkpoints to on.
19. Set log_statement to ddl.
20. work_mem
