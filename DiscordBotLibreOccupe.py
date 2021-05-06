import discord
import os  # To get the token in secure .env file
from dotenv import load_dotenv  # To load the env file
import datetime
import asyncio  # used to wait in the loop

load_dotenv()  # Loads the env file (with a secure token)

client = discord.Client()

# Configuration
autoRespondIfChannelIsOccupied = True
autoRespondIfOccupiedDelay = 60  # s
specialMessageForCentu = False
onlyManageChannelsWithThisString = "︱"  # (unicode U+FE31)
autoFreeChannels = True
delayToFreeAChannel = 660  # seconds /!\ Can't be below 600s because discord prevents modifying too often
freeString = "libre"
occupiedString = "occupé\N{Octagonal Sign}"
messageToFreeAChannel = "!libre"

# Main variables
myChannelsInfo = []  # The list of channels that contain the sign defined in configuration
deletedChannelsIDs = []

# =============================================================== #
# Events


@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")

    # Build our lists
    channels = client.get_all_channels()  # All channels, all servers, including voice
    for channel in channels:
        if (onlyManageChannelsWithThisString in str(channel.name) and
                type(channel) is discord.TextChannel):
            myChannelsInfo.append(ChannelInfo(channel))

    # Initialize channel names
    for chanInfo in myChannelsInfo:
        await actualizeChannelName(chanInfo)


@client.event
async def on_message(message):
    # Ignore messages from this bot
    if message.author == client.user:
        return

    # Find the things we stored about this channel
    for chanInfo in myChannelsInfo:
        if chanInfo.channel.id == message.channel.id:
            channelInfo = chanInfo
            break
    else:  # this happens only if we didn't break from the for loop (we didn't find the id)
        # so we just ignore messages in other channels
        return
    # We found a channel
    channel = channelInfo.channel

    # Special case for Centu (joke)
    if "yo" in message.content and specialMessageForCentu:
        await message.channel.send("Arrête <@276366891721687040> !")

    # Define specific roles (returns None if there's no such role in this guild)
    roleProf = discord.utils.find(lambda m: "[Prof]" in m.name, message.guild.roles)
    roleEtudiant = discord.utils.find(lambda m: "tudiant" in m.name, message.guild.roles)  # No E to avoid mistakes
    roleVacancier = discord.utils.find(lambda m: "Vacancier" in m.name, message.guild.roles)

    # Find the channel choisis-ton-niveau
    chanChoisis = await find_choisis_ton_niveau(channel.guild)

    # Check if the user has no role (or vacancier only)
    if len(message.author.roles) == 1 or (roleVacancier in message.author.roles and len(message.author.roles) == 2):
        msg = discord.Embed(
            title="Choisis un rôle",
            description=f"<@{message.author.id}> tu devrais aller choisir le rôle prof dans {chanChoisis.mention}. ",
            colour=discord.Colour.green()
        )
        await channel.send(embed=msg)
        return

    # Check if a "Etudiant" is speaking in the wrong channel
    if roleEtudiant in message.author.roles and roleProf not in message.author.roles:
        if "sup" not in channel.name and ("maths" in channel.name or
                                          "physique" in channel.name or
                                          "chimie" in channel.name):  # TODO add exceptions ?
            # Check if we didn't warn them recently
            currentTime = datetime.datetime.utcnow().timestamp()  # in s since epoch
            delta_t = currentTime - channelInfo.timeOfLastBotWarningStudent  # in seconds
            # Case where it's been long enough to warn again
            if delta_t > autoRespondIfOccupiedDelay:
                channelInfo.timeOfLastBotWarningStudent = currentTime  # store the time of this message
                # Send a message to the "etudiant"
                msg = discord.Embed(
                    title="Mauvais canal",
                    description=(f"<@{message.author.id}> tu devrais demander dans le canal dédié au supérieur. \n"
                                 f"Si tu souhaites aider un élève tu peux aller "
                                 f"choisir le rôle prof dans {chanChoisis.mention}. "),
                    colour=discord.Colour.green()
                )
                await channel.send(embed=msg)
            return

    # Cases where the message comes from a student
    if roleProf not in message.author.roles:
        # If channel is free, let's set it as occupied
        if channelInfo.storedMsgID == 0:
            # Check if this student isn't already using another channel
            for c in myChannelsInfo:
                if c.storedAuthorID == message.author.id:
                    # Check if we didn't warn in this channel recently
                    currentTime = datetime.datetime.utcnow().timestamp()  # in s since epoch
                    delta_t = currentTime - channelInfo.timeOfLastBotWarningWrongChannel  # in seconds
                    # Case where it's been long enough to warn again
                    if delta_t > autoRespondIfOccupiedDelay:
                        channelInfo.timeOfLastBotWarningWrongChannel = currentTime  # store the time of this message
                        # Send a message
                        msg = discord.Embed(
                            title=f"Tu as déjà un autre canal \N{SMILING FACE WITH HALO}",
                            description=(f"<@{message.author.id}> le canal {c.channel.mention}"
                                         "est déjà reservé pour toi."),
                            colour=discord.Colour.red()
                        )
                        msg.set_footer(text=("Attends qu'un prof te réponde dans l'autre canal, "
                                             "car on ne traîte qu'une demande à la fois par élève ."))
                        await channel.send(embed=msg)
                    # We can now return (message is ignored)
                    return
            # Author validated ! Let's set the channel as occupied : reset the channelInfo variables
            channelInfo.storedMsgID = message.id
            channelInfo.storedAuthorID = message.author.id
            channelInfo.timeOfLastBotWarningOccupied = 0
            channelInfo.timeOfLastBotWarningWrongChannel = 0
            channelInfo.timeOfLastBotWarningStudent = 0
            channelInfo.aProfIntervened = False
            # Send a message
            msg = discord.Embed(
                title=f"Canal reservé automatiquement \N{OK HAND SIGN}",
                description=(f"Ce canal est maintenant occupé par {message.author.mention} \n "
                             "Pense à poster ton exo, ce que tu as commencé à  faire, "
                             "et la question où tu bloques."),
                colour=discord.Colour.green()
            )
            msg.set_footer(text=(f"Merci de ne pas demander dans un autre canal, "
                                 "si un prof est dispo il viendra ici. \n"
                                 "Le canal se libèrera tout seul après réponse d'un prof."))
            await channel.send(embed=msg)
            # Change the channel name
            await actualizeChannelName(channelInfo)

        # If channel is not free check who's talking
        else:
            # Search for the message we stored (from the student occupying this channel)
            try:
                storedMessage = await channel.fetch_message(channelInfo.storedMsgID)
            except:
                print("Exception : can't find last message")
                storedMessage = None
            # Channel is not free, but it's the right student
            if message.author.name == storedMessage.author.name:
                channelInfo.storedMsgID = message.id  # store the new message's id as reference
                # If a prof already answered, and the auto free option is on, launch a timer to free the channel
                if channelInfo.aProfIntervened and autoFreeChannels:
                    await waitAndFreeTheChannel(channelInfo)
            # Channel is not free and it's another student : warn them
            elif autoRespondIfChannelIsOccupied:
                # Check if we didn't warn them recently
                currentTime = datetime.datetime.utcnow().timestamp()  # in s since epoch
                delta_t = currentTime - channelInfo.timeOfLastBotWarningOccupied  # in seconds
                # Case where it's been long enough to warn again
                if delta_t > autoRespondIfOccupiedDelay:
                    channelInfo.timeOfLastBotWarningOccupied = currentTime  # store the time of this message
                    msg = discord.Embed(
                        title="Canal Occupé",
                        description=f"<@{message.author.id}> merci de passer dans un canal libre.",
                        colour=discord.Colour.orange()
                    )
                    await channel.send(embed=msg)
    # The message comes from a [Prof]
    else:
        # Remember that a prof has talked in this channel (for the auto free)
        channelInfo.aProfIntervened = True
        # Case where the prof is using the command to reset the channel
        if messageToFreeAChannel in message.content:
            # Reinitialize the object
            channelInfo.clearData()
            # Send a message
            msg = discord.Embed(
                title="Canal Libéré",
                description="",
                colour=discord.Colour.green()
            )
            msg.set_footer(
                text=f"Le nom du canal peut mettre jusqu'à 10min à s'actualiser, c'est une limitation de Discord.")
            await channel.send(embed=msg)
            await actualizeChannelName(channelInfo)
        # Case where the prof isn't using a command, launch a timer to free the channel if the option is on
        elif autoFreeChannels:
            await waitAndFreeTheChannel(channelInfo)


@client.event
async def on_message_delete(message):
    # Find the things we stored about this channel
    for chanInfo in myChannelsInfo:
        if chanInfo.channel.id == message.channel.id:
            channelInfo = chanInfo
            break
    else:  # this happens only if we didn't break from the for loop (we didn't find the id)
        # so we just ignore messages in other channels
        return
    # We found a channel
    # Check if the deleted message was the one stored as occupying the channel
    if message.id == channelInfo.storedMsgID:
        channelInfo.clearData()
        # free the room after the usual delay, even if the variable autoFreeChannels is true
        await waitAndFreeTheChannel(channelInfo)


@client.event
async def on_guild_channel_create(channel):
    if onlyManageChannelsWithThisString in channel.name and type(channel) is discord.TextChannel:
        channelInfo = ChannelInfo(channel)
        myChannelsInfo.append(channelInfo)
        await actualizeChannelName(channelInfo)


@client.event
async def on_guild_channel_delete(channel):
    for c in myChannelsInfo:
        if c.channel.id == channel.id:
            # TODO ! How to remember that I removed this ?
            deletedChannelsIDs.append(c.channel.id)
            myChannelsInfo.remove(c)
            break
    # It doesn't matter if we didn't find it, it's just not a channel managed by the bot


@client.event
async def on_guild_channel_update(before, after):
    allChannels = await after.guild.fetch_channels()
    channel = None
    for c in allChannels:
        if c.name == after.name and type(c) is discord.TextChannel:
            channel = c
            break
    # End of for loop, "else" is used if we didn't break so we didn't find it
    else:
        print("This shouldn't happen ! (in channel_update)")

    # If name lose the symbol signaling that we should monitor the channel
    if onlyManageChannelsWithThisString in before.name and type(channel) is discord.TextChannel:
        if onlyManageChannelsWithThisString not in after.name:
            for c in myChannelsInfo:
                if c.channel is channel:
                    deletedChannelsIDs.append(c.channel.id)
                    myChannelsInfo.remove(c)
                    return
    # If name gained the symbol
    if onlyManageChannelsWithThisString in after.name and type(channel) is discord.TextChannel:
        if onlyManageChannelsWithThisString not in before.name:
            chanInfo = ChannelInfo(channel)
            myChannelsInfo.append(chanInfo)
            print("Channel name should change")
            await actualizeChannelName(chanInfo)
    # If name kept the symbol
    if onlyManageChannelsWithThisString in before.name and onlyManageChannelsWithThisString in after.name:
        if freeString not in after.name and occupiedString not in after.name:
            for c in myChannelsInfo:
                if c.channel.id is channel.id:
                    await actualizeChannelName(c)


# ============================================================== #
# Function(s)


async def waitAndFreeTheChannel(channelInfo):
    message_id = channelInfo.storedMsgID  # save the id for comparison
    channel_id = channelInfo.channel.id
    await asyncio.sleep(delayToFreeAChannel)  # wait to free the channel
    # Check if the channel still exists
    for delID in deletedChannelsIDs:
        if delID == channel_id:
            # The channel was deleted, no need to do anything
            return
    # free the channel if no other message came while waiting
    if channelInfo.storedMsgID == message_id:
        channelInfo.clearData()
        await actualizeChannelName(channelInfo)
    else:
        print("Vérification réussie ! Le 2nd message a bien remplacé le 1er.")


async def actualizeChannelName(channelInfo):
    channel = channelInfo.channel
    storedMsgID = channelInfo.storedMsgID
    # Case where we want to free the channel
    if storedMsgID == 0:
        # Make sure name contains "libre"
        if freeString not in channel.name:
            if occupiedString in channel.name:
                newName = channel.name.replace(occupiedString, freeString)
            else:  # Initializing
                newName = channel.name + freeString
            # Now change the name
            await channel.edit(name=newName)
    # Case where the channel becomes occupied
    else:
        if occupiedString not in channel.name:
            if freeString in channel.name:
                newName = channel.name.replace(freeString, occupiedString)
            else:  # Initializing
                newName = channel.name + occupiedString
            # Now change the name
            await channel.edit(name=newName)


async def find_choisis_ton_niveau(guild):
    tempChans = await guild.fetch_channels()
    for c in tempChans:
        if "choisis-ton-niveau" in c.name:
            return c


# ============================================================== #
# Class(es)


class ChannelInfo:
    def __init__(self, channel):
        self.channel = channel
        self.storedMsgID = 0
        self.storedAuthorID = 0
        self.timeOfLastBotWarningOccupied = 0
        self.timeOfLastBotWarningWrongChannel = 0
        self.timeOfLastBotWarningStudent = 0
        self.aProfIntervened = False

    def clearData(self):
        self.storedMsgID = 0
        self.storedAuthorID = 0
        self.timeOfLastBotWarningOccupied = 0
        self.timeOfLastBotWarningWrongChannel = 0
        self.timeOfLastBotWarningStudent = 0
        self.aProfIntervened = False


# ================================================================ #

client.run(os.getenv('TOKEN'))
