# sets up the nismod database
# uses the SFTP server to get datafiles for database

import pysftp, re, subprocess
from getpass import getpass

# ask for SFTP username
username = input("Username:")
# ask for SFTP password
password = getpass("Enter password for " + username + ":")

cnopts = pysftp.CnOpts()
cnopts.hostkeys = None

# establish connection to SFTP server
with pysftp.Connection('ceg-itrc.ncl.ac.uk', username=username, password=password, cnopts=cnopts) as sftp:

	# change to directory to database
	with sftp.cd('project/database'):

		# get api wheel

		# get list of files
		file_names = sftp.listdir()

		# find wheel file
		for file in file_names:
			wheel = re.search(".whl", file)

			# when found, get from server
			if wheel:
				sftp.get(file)

				# install api from wheel file
				subprocess.run(['sudo', 'pip3', 'install', file])

				# following install, delete wheel
				subprocess.run(['sudo', 'rm', file])

				# end search for file
				break

		# get database files
		# pull migration files
		with sftp.cd('nismod-db-vm/migrations'):

			# get list of files
			file_names = sftp.listdir()

			# loop through files
			for file in file_names:

				if file[0:2] == 'up':

					# get sql file
					sftp.get(file)

					# run sql file silently
					subprocess.run(['psql', '-U', 'vagrant', '-d', 'nismod-db', '-q', '-f', file])

					# remove sql file - no longer needed
					subprocess.run(['sudo', 'rm',  file])

		# get files to populate database and populate
		with sftp.cd('nismod-db-vm'):

			sftp.get('copy_data_to_database.sql')

			# database hydration through sql file
			# intervals
			subprocess.run(['psql', '-U', 'vagrant', '-d', 'nismod-db', '-q', '-f', 'copy_data_to_database.sql'])
