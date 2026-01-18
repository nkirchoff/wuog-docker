import requests
from bs4 import BeautifulSoup
import csv
import os.path

# Ask for the URL of the webpage to scrape
url = input("Enter the URL of the webpage to scrape: ")

# Send a GET request to the URL
response = requests.get(url)

# Parse the HTML code using Beautiful Soup
soup = BeautifulSoup(response.content, 'html.parser')

# Find all the song items on the page
song_items = soup.find_all('tr', {'class': 'spin-item'})

# Check if the CSV file exists
if os.path.isfile('song_data.csv'):
    # If the file exists, open it in read mode and read the existing data
    with open('song_data.csv', mode='r', newline='') as file:
        reader = csv.reader(file)
        song_data = [row for row in reader]
else:
    # If the file does not exist, create it and write the header row
    with open('song_data.csv', mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Artist', 'Song', 'Album'])
    song_data = []

# Append the new song data to the CSV file
with open('song_data.csv', mode='a', newline='') as file:
    writer = csv.writer(file)
    for song_item in song_items:
        artist = song_item.find('span', {'class': 'artist'}).text
        song = song_item.find('span', {'class': 'song'}).text
        album = song_item.find('span', {'class': 'release'})
        
        # Check if album information is available
        if album:
            album = album.text
        else:
            album = 'N/A'
        
        # Check if the song is already in the file
        if [artist, song, album] not in song_data:
            # Write the extracted information to the CSV file
            writer.writerow([artist, song, album])
            # Add the new song to the existing data list
            song_data.append([artist, song, album])

# Print a message to confirm that the CSV file has been updated
print("CSV file updated successfully.")