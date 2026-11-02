"""
College Online Examination System - Backend Configuration
Gauhati University FYUGP Academic Context
"""

# Register PyMySQL as MySQLdb for MySQL 8.x database backend compatibility
try:
    import pymysql
    pymysql.install_as_MySQLdb()
except ImportError:
    pass
