from setuptools import setup, find_packages
import os

version = "0.0.1"

setup(
    name='tx.cyrus',
    version=version,
    description="Twisted Cyrus client library",
    long_description=open(
        os.path.join('tx', 'cyrus', 'README.rst')).read() + "\n"
    + open(os.path.join("docs", "HISTORY.txt")).read(),
    classifiers=[
        "Programming Language :: Python",
        "Topic :: Software Development :: Libraries :: Python Modules"],
    keywords='',
    author='Ryan Northey',
    author_email='ryan@3ca.org.uk',
    url='http://code.3ca.org.uk',
    license='GPL',
    packages=find_packages(exclude=['ez_setup']),
    namespace_packages=['tx', 'tx.cyrus'],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        'twisted',
        'setuptools'],
    entry_points="""
    # -*- Entry points: -*-
    """)
