import numpy as np
import math
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pyaudio
import mido
from enum import Enum
from collections import deque
import scipy.signal as sig
import tkinter as tk
import random


class waveforms(Enum):
    """
    Standard set of waveforms.
    """
    zero=0
    sin=1
    tri=2
    square=3
    saw=4
    other=5


class SynthGenerator:
    """
    Generates waveforms using pyaudio. It's controlled by mido with python-rtmidi.
    It runs a seperate thread to play the notes. Each notes is played in a seperate pyaudio stream.
    Up to 10 notes can play at once.

    It can play sin (sine), tri (triangle), square, and saw (sawtooth) waveforms.

    The numpy version is 1.26.0.

    """
    def __init__(self, waveform='sin', root=None, decimate=False):
        #Standard pyaudio values
        self.__SAMPLE_RATE = 48000 
        self.__BLOCKSIZE = 512 #How many samples aare processed at once, often also called chunksize. This value should not be changed.
        self.__MAX_NOTES = 10 #Max number of notes it can play at once
        self.__DECIMATE = decimate #Decimation means it processes at 48 kHz, then the output is 16kHz
        
        self.__PITCHWEEL_STRENGTH = np.float32(0.01) #For use on a midi keyboard, the effect of the pithcwheel is scaled
        self.__KEY_ATTACK_STRENGTH = np.float32(0.02) #For use when attack strength is measured on midi keyboard
        self.__VOLUME = np.float32(0.2) #Global volume scale
        self.ROOT_TK_WINDOW = root #The tkinter isntance if SynthUI is used.

        self.phaseLvl = 0

        if(self.ROOT_TK_WINDOW == None):
            self.UI_PRESENT = False
        else:
            self.UI_PRESENT = True

        #When decimation is used, sample rate must be 48 kHz
        if(self.__DECIMATE):
            if(self.__SAMPLE_RATE==48000):
                self.__DEC_N=4
            else:
                raise ValueError("Invalid sample rate for decimation. Use 48000")
        else:
            self.__DEC_N=1

        #Used to quickly pause the stream
        self.__PAUSE = False
        self.__IS_PAUSED = False
        self.__STREAM_ACTIVE = False

        self.NumHarmonics = 0 
        self.harmonicsVol = 0.2 #Voume of the harmonics added on

        self.setWaveForm(waveform)
        self.genWaveArray()
        self.setAdsr(5, 10)
        self.setWobble(15)
    
        #Used to pass sound values for plotting
        self.wavDeque = deque()

        #Used for real time processing
        self.pitchWheelFreq = 0 #How many Hz up or down the pitch wheel changes all current notes
        self.NumNotesPressed = 0 
        self.randLvl = 0 #scales the amount of randomness aded to the notes, also called detuning
        self.justIntonation = False #Changes the note spacing from equal temperment (every note is the same distance aprat) to just intonation (every note is scaled from a root pitch)
        self.setJustRoot(0) 
        #critical array, holds the current active notes, notes are removed when not active
        self.__activeNotes = [Note(pitch=0, volume=0, state=NoteStates.NULL) for i in range(self.__MAX_NOTES)]



    def setJustRoot(self, pitch):
        """
        Sets the root note and root frequency when just intonation is used. 
        """
        self.justRootPitch = pitch
        pitch+=60 #hardcoded 4th octave as where base frequency is
        self.justRootFreq = 440 * 2**((pitch - 69) / 12) #Converts midi pitch to frequency

    def setAdsr(self, attack, decay):
        """
        Initialize values used for ADSR or Attack -> Decay -> Sustain -> Release.
        """
        attackProfile = np.linspace(0, 1, self.__BLOCKSIZE*(attack)+1).astype(np.float32)
        decayProfile = np.linspace(1, 0, self.__BLOCKSIZE*(decay)+1).astype(np.float32)
        
        self.pauseStream() #Pauses stream if currently streaming audo
        #Values and profile used for ADSR
        self.__AttackCycles = attack #a 'cycle' is 512 samples or one block
        #It increases volume linearly for num cycles
        self.attackProfile = attackProfile

        self.__DecayCycles = decay
        self.decayProfile = decayProfile
        self.continueStream()

    def setWobble(self, wobbleSpeed):
        self.pauseStream()
        #Updates in real time
        self.wobbleRate = np.clip(wobbleSpeed, 5, 100).astype(np.int16)
        self.wobbleMag = 0
        self.wobbleIndex = 0

        #Constant
        self.__WOBBLE_MAG = 1 #Float, typically 0-2 scales the frequency delta based on the aftertouch value
        self.__WOBBLE_PROFILE = np.linspace(0, 2*np.pi, self.wobbleRate)
        self.__WOBBLE_PROFILE = np.sin(self.__WOBBLE_PROFILE).astype(np.float32)
        self.continueStream()
    
    def setVolume(self, volume):
        """
        Sets the global volume variable.
        """
        self.__VOLUME = np.clip(volume, 0, 1).astype(np.float32)

    def getVolume(self):
        """
        Returns the global volume variable.
        """
        return self.__VOLUME


    def startStream(self):
        """
        Starts reading audio and midi stream.
        It runs in a seperate thread with a callback set in the pyaudio inisitalization.
        """
        # Attempts to open a midi port
        try:
            self.__midiIn = mido.open_input() # Get the first available input port
            print(f"Connected to MIDI input: {self.__midiIn.name}")
        except OSError:
            print("No MIDI input device found.")
            exit()
        
        # Open the audio output streams
        self.__pyaudioPort = pyaudio.PyAudio()

        # Initializes a pyaudio stream
        self.__audioStream = self.__pyaudioPort.open(format = pyaudio.paInt16,
                                        channels          = 1,
                                        frames_per_buffer = self.__BLOCKSIZE // self.__DEC_N, #DEC_N is just 1 with no decimation
                                        rate              = self.__SAMPLE_RATE // self.__DEC_N,
                                        input             = False,
                                        output            = True,
                                        stream_callback=self.runStream)

        self.__audioStream.start_stream()   
        self.__STREAM_ACTIVE = True

        #self.initMoveAvg()
        self.initFilter()

        print( '*******************')
        print( '** Ready to play **')
        print( '*******************')     
    
    def getMidiInput(self):
        """
        Collects Midi input and updates values accordingly.
        """
        midi = self.__midiIn.iter_pending()

        #Collect midi input and update relevant variables
        for message in midi:
            print(message)
            if message.type == 'note_on':
                self.NumNotesPressed +=1
                pitch = message.note
                vel = message.velocity*self.__KEY_ATTACK_STRENGTH + 0.2
                self.addNote(pitch, vel)
            elif message.type == 'note_off':
                self.NumNotesPressed -=1
                pitch = message.note
                self.startDecayNote(pitch)
            elif message.type == 'control_change':
                None
            elif message.type == 'aftertouch':
                #Pressing ard on midi keyboard. Adds 'wobble' to sound.
                self.wobbleMag = message.value*self.__WOBBLE_MAG

            elif message.type == 'pitchwheel':
                #Bends the frequency of all current notes.
                self.pitchWheelFreq = round(message.pitch*self.__PITCHWEEL_STRENGTH)

    def runStream(self, in_data, frame_count, time_info, status):
        """
        Callback for pyaudio, looped continously.
        """
        #Pauses stream
        if self.__PAUSE:
            self.__IS_PAUSED = True
        while self.__PAUSE:
            None 
        
        self.getMidiInput() #Updates midi input
        
        #Adjusts all pitches at the same time
        self.notesFreqAdjust = self.pitchWheelFreq

        self.wobbleIndex += 1
        self.wobbleIndex %= self.wobbleRate

        if self.wobbleMag > 0:
            self.notesFreqAdjust += self.__WOBBLE_PROFILE[self.wobbleIndex]*self.wobbleMag

        #Set 512 samples to be zero
        data = np.zeros(self.__BLOCKSIZE).astype(np.float32)

        try:
            #Generate 512 samples for each note
            for note in self.__activeNotes:
                if note.state != NoteStates.NULL:
                    data += self.genWave(note) 

            
            #filtered_low, self.zi_low = sig.lfilter(self.b_low, self.a_low, data, zi=self.zi_low)
            # filtered_high, self.zi_high = sig.lfilter(self.b_high, self.a_high, data, zi=self.zi_high)
            # filtered_data = filtered_high
            # #print(filtered_data)
            # data = (filtered_data * 32767.0).astype(np.int16)
            # # Apply the filter using lfilter
            # data = np.concatenate((self.PREV_VALS_AVG, data))
            # data = sig.lfilter(self.__AVG_B, 1, data)
            # self.PREV_VALS_AVG = data[-self.__AVG_WINDOW:]
            # data = data[self.__AVG_WINDOW:]

        #Happens on very rare occasion. 
        except IndexError: 
            None

        #Clips data to 16 bit integer
        data = np.clip(data, -2**15+1, 2**15-1).astype(np.int16)

        #If the signal is decimated, this converts 48 kHz sampling to 16 kHz sampling
        if self.__DECIMATE:
            data = sig.decimate(data, 4).astype(np.int16)
        
        #Passes samples to a deque for plotting
        self.wavDeque.append(data)

        #Converts samples to binary for DAC
        data = data.tobytes()

        #Streams data to dac with pyaudio
        return (data, pyaudio.paContinue)

    def initMoveAvg(self):
        self.__AVG_WINDOW = 5

        self.__AVG_B = np.ones(self.__AVG_WINDOW) / self.__AVG_WINDOW

        self.PREV_VALS_AVG = np.zeros(self.__AVG_WINDOW).astype(np.float32)

    def initFilter(self):
        # Filter design (Butterworth filters are commonly used)
        def create_filter(cutoff, order, filter_type):
            nyquist_freq = 0.5 * self.__SAMPLE_RATE
            normalized_cutoff = cutoff / nyquist_freq
            b, a = sig.butter(order, normalized_cutoff, btype=filter_type, analog=False)
            return b, a
        
        order = 5

        self.b_low, self.a_low = create_filter(20000, order, 'low')
        self.b_high, self.a_high = create_filter(20, order, 'high')

        # Initialize filter states (important for real-time processing)
        self.zi_low = sig.lfilter_zi(self.b_low, self.a_low)
        self.zi_high = sig.lfilter_zi(self.b_high, self.a_high)

    def pauseStream(self):
        """
        Pauses stream.
        """
        if self.__STREAM_ACTIVE:
            self.__PAUSE = True
            while not self.__IS_PAUSED:
                None
    
    def continueStream(self):
        """
        Un-pauses stream.
        """
        if self.__STREAM_ACTIVE:
            self.__PAUSE = False
            self.__IS_PAUSED = False

    def stopStream(self):
        """
        Safely stops the stream.
        """

        print("\nExiting...")

        # Close up all of the stream properly
        self.__STREAM_ACTIVE = False
        self.__audioStream.stop_stream()
        self.__audioStream.close()
        self.__pyaudioPort.terminate()

        #Closes the midi port.
        self.__midiIn.close()

    def genWave(self, note):
        """
        Handles the different states of the notes.
        The states are changed on midi input.
        """
        # Changes the volume based the notes currnet state. 
        # This volume is either a scaler or numpy array depending on state.
        if(note.state==NoteStates.OFF):
            soundData = np.zeros(self.__BLOCKSIZE).astype(np.float32)
            return soundData

        elif(note.state==NoteStates.DECAY):
            # Creates an array of volumes, one for each sample, using the decay profile array
            start = note.profile_phase_index*self.__BLOCKSIZE
            end = start + self.__BLOCKSIZE
            note.volume = note.init_volume * self.decayProfile[start:end]

            # If the decay profile array has been iterated through, delete the note 
            if(note.profile_phase_index >= self.__DecayCycles):
                note.profile_phase_index=0
                self.deleteNote(note)
            else:
                note.profile_phase_index += 1 #Each block iterates through the decay profile array

        elif(note.state==NoteStates.ATTACK):
            # Creates an array of volumes, one for each sample, using the attack profile array
            start = note.profile_phase_index*self.__BLOCKSIZE
            end = start + self.__BLOCKSIZE
            note.volume = note.init_volume * self.attackProfile[start:end]

            # If the end of the attack profile array is reached, change the note state to on
            if(note.profile_phase_index >= self.__AttackCycles):
                note.profile_phase_index=0
                note.state=NoteStates.ON
            else:
                note.profile_phase_index += 1 #Each block iterates through the attack profile array

        elif(note.state==NoteStates.ON):
            note.volume = note.init_volume
        
        soundData = self.genSoundData(note)
        
        return soundData


    def genSoundData(self, note):
        """
        Collects 32 (2 byte) samples from the wave array. 
        Adjusts each sample for volume and rounds.
        Sound Generation is done by gathering samples from an a large sample array of the current waveform.
        Done using vectorization for speed.
        """
        note.frequency = note.init_frequency + self.notesFreqAdjust

        #STEPS_PER_CYCLE = np.float32(self.__WAVE_SAMPLES/ self.__SAMPLE_RATE)
        #Incriments through waveform array, inriments with floats to make frequencies more accurate
        phase_increment = note.frequency * self.__STEPS_PER_CYCLE
        end = (note.phase_index + phase_increment * (self.__BLOCKSIZE)) #Always generate more phases then needed
        
        # 1. Create an array of phase indices:
        phases = np.arange(note.phase_index, end, phase_increment)
        
        phases = phases[:512] #Limit the number of phases to the correct amount
        
        phases = np.round(phases).astype(np.uint16) #Phases are calculated using a float, then round, helps with frequency accuracy

        # 2. Wrap the phase indices using the modulo operator (vectorized):
        phases %= self.__WAVE_SAMPLES
        
        #3. Store the last phase index for the next block
        note.phase_index = (phases[-1]+phase_increment) % self.__WAVE_SAMPLES
        
        # 4. Use the phase indices to index into the wavetable (vectorized):
        #The note.volume can be scaler or an array of 512 values, depending on what state the note is in.
        soundData = np.around(self.WaveArray[phases] * note.volume * self.__VOLUME).astype(np.float32)
        
        return soundData

    def lowPassFilter(self, signal):
        """Applies a first-order IIR low-pass filter to a signal using vectorization.
        """
        filteredSignal = sig.lfilter(self.LowPassInvAlpha, self.LowPassAlpha, signal)

        return filteredSignal.astype(signal.dtype)

    def setlowPassFreq(self, lowPassFreq):
        """
        Update the frequency and other values needed for the low pass filter.
        """
        if lowPassFreq <= 0 or lowPassFreq >= self.__SAMPLE_RATE / 2:
            raise ValueError("Cutoff frequency must be between 0 and Nyquist frequency (sample_rate / 2)")
        self.lowPassFreq = lowPassFreq
        self.LowPassAlpha = 1 / (1 + (2 * np.pi * lowPassFreq / self.__SAMPLE_RATE))
        self.LowPassInvAlpha = 1-self.LowPassAlpha

        # nyquist_freq = 0.5 * self.__SAMPLE_RATE
        # if lowPassFreq >= nyquist_freq or lowPassFreq <= 0:
        #     print(f"Invalid cutoff frequency: {lowPassFreq} Hz. Must be between 0 and {nyquist_freq} Hz")
        #     return None

        # normalized_cutoff = lowPassFreq / nyquist_freq
        # self.LowPassInvAlpha, self.LowPassAlpha = sig.butter(10, normalized_cutoff, btype='low', analog=False)

    def getFreqs(self):
        """
        Returns frequency of all currently on notes.
        """
        freqs = []
        for i, note in enumerate(self.__activeNotes):
            if note.state == NoteStates.ON:
                freqs.append(self.__activeNotes[i].init_frequency)
        
        return freqs

    def getMinNote(self):
        minIndex = None
        minFreq = None
        for i, note in enumerate(self.__activeNotes):
            if note.state == NoteStates.ON:
                if minIndex == None:
                    minFreq = self.__activeNotes[i].init_frequency
                    minIndex = i
                else:
                    freq = self.__activeNotes[i].init_frequency
                    if freq < minFreq:
                        minFreq = freq
                        minIndex = i
        
        return minIndex

    def getStartPhase(self, newFreq):
        """
        Gets a phase for a note that will create a nice sounding interferance pattern.
        """
        freqs = self.getFreqs()
        if len(freqs)==0:
            return 0
        
        baseIndex = self.getMinNote()
        if baseIndex == None:
            return 0

        baseFreq = self.__activeNotes[baseIndex].init_frequency
        basePhase = self.__activeNotes[baseIndex].phase_index
        basePhaseInc = baseFreq * self.__STEPS_PER_CYCLE
        numSamplesPerCycle = self.__WAVE_SAMPLES/basePhaseInc
        if newFreq > baseFreq:
            phase = self.__WAVE_SAMPLES/np.pi
            return phase
        else:
            return 0

    def addNote(self, pitch, velocity=0):
        """
        Starts Note, uses non-zero phase if other notes are present.
        """
        noteAdded=False
        for i, note in enumerate(self.__activeNotes):
            if note.state == NoteStates.NULL:
                if not noteAdded:
                    noteAdded=True
                    #Initializes note object.
                    newNote = Note(pitch, velocity, randLvl=self.randLvl)
                    
                    if(self.justIntonation): #Changes intonation to just intonation
                        newNote.setJustIntonation(self.justRootFreq, self.justRootPitch)
                    
                    #phase = self.getStartPhase(newNote.init_frequency)
                    newNote.setPhase(self.__WAVE_SAMPLES/np.pi)

                    self.__activeNotes[i] = newNote #Adds note to array of active notes.
            else:
                self.__activeNotes[i].setPhase(0)

                

    def deleteNote(self, note):
        #Finds note object in array of active note objects. Deletes note by replacing note object with placeholder note.
        for i, n in enumerate(self.__activeNotes):
            if n==note:
                #Add a null note to the list
                self.__activeNotes[i]=Note(pitch=0, volume=0, state=NoteStates.NULL)

    def findMinPitch(self):
        """
        Finds the minimum pitch.
        """
        pitch = []
        for note in self.__activeNotes:
            if note.state != NoteStates.OFF or note.state != NoteStates.NULL:
                pitch.append(note.pitch)
        if len(pitch)==0:
            return 0
        return min(pitch)
    
    def startDecayNote(self, pitch):
        """
        Starts the decay part of a note.
        """
        for i, note in enumerate(self.__activeNotes):
            if note.state != NoteStates.NULL:
                if note.pitch==pitch:
                    note.state=NoteStates.DECAY

    def getNotes(self):
        """
        Gets text representation of the notes.
        """
        notes = []
        for note in self.__activeNotes:
            notes.append(note.note)
        return notes
    

    def initAnim(self):
        """
        Initialize a graph for displaying the current sound output.
        Dispays a quarter of the values. Displays the waveform based on the maximum value.
        It moves the waveform across the plot, moving it about 1/8 of the values every time it updates.
        Usually updated every 100 ms. 
        """
        #NANIM_BUFFER_SIZE is the number of samples shown on display
        #4 comes from every 4th piece of sampling being used

        if self.__DECIMATE:
            self.ANIM_DEC_N = 1
        else:
            self.ANIM_DEC_N = 4
        
        self.ANIM_BUFFER_SIZE = int(2048/4)
        self.ANIM_NUM_CHUNKS = 20
        self.ANIM_NUM_SAMPLES = int(self.__BLOCKSIZE/4 *self.ANIM_NUM_CHUNKS )
        self.WAV_MOVE_DIS = np.int32(int(self.ANIM_BUFFER_SIZE/8)) #Move 1/8th of the ANIM_BUFFER_SIZE
        self.wavMoveIter = np.int32(0)
        self.TIME_DISPLAYED = self.ANIM_BUFFER_SIZE/self.__SAMPLE_RATE*4

        #Matplotlib setup
        if not self.UI_PRESENT:
            plt.ion()  # Turn on interactive mode

        self.fig, self.ax = plt.subplots()
        self.line, = self.ax.plot(np.zeros(self.ANIM_BUFFER_SIZE))
        self.ax.set_ylim(-(2**15+1)/2, (2**15-1)/2)
        self.ax.set_xlim(0, self.ANIM_BUFFER_SIZE)
        self.ax.set_title("Real Time Waveform (Updated every 100ms)")
        #Remove x-axis and y-axis ticks and labels
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.ax.set_ylabel("Ouput to DAC (Not Full Range)")
        self.ax.set_xlabel("Duration: 4.26 ms or 2048 Samples")

        self.audioBuffer = np.zeros(self.ANIM_BUFFER_SIZE, dtype=np.int16)
        
        if(self.UI_PRESENT):
            self.canvas = FigureCanvasTkAgg(self.fig, master=self.ROOT_TK_WINDOW)
            self.canvas.draw()
            return self.canvas.get_tk_widget()


    def animSoundUpdate(self):
        """
        The callback for drawing a moving animation of the current sound output.
        """
        #Check num chunks, if greate than ANIM_NUM_CHUNKS remove some
        numBlocks = len(self.wavDeque) 
        if numBlocks >= self.ANIM_NUM_CHUNKS:
            for i in range(numBlocks - self.ANIM_NUM_CHUNKS):
                data = self.wavDeque.popleft()
                #self.check_block(data)
        else:
            return #not enough chunks

        #Collect desired chunks into an array, then concatenate all chunks to create single 1d array
        audio_samples = []
        while len(self.wavDeque) > 0:
            data = self.wavDeque.popleft()
            #self.check_block(data)
            audio_samples.append(data)
        audio_samples = np.concatenate(audio_samples)

        #Get max index, used to position waveform
        max_index = np.argmax(audio_samples)

        #Get every 4th chunk to reduce necessary processing
        audio_samples = audio_samples[::self.ANIM_DEC_N]
        #print("Len audio_amples: ", len(audio_samples))
        max_index = max_index//self.ANIM_DEC_N 

        #Iter is used to position the waveform relative to the max of the waveform
        self.wavMoveIter += self.WAV_MOVE_DIS
        self.wavMoveIter %= self.ANIM_NUM_SAMPLES

        start = (max_index + self.wavMoveIter) % self.ANIM_NUM_SAMPLES #Handle wrap around
        end = start + self.ANIM_BUFFER_SIZE

        #Handle wrap around
        if(end > self.ANIM_NUM_SAMPLES):
            end = end % self.ANIM_NUM_SAMPLES
            audio_samples = np.concatenate((audio_samples[start:], audio_samples[:end]))
            #print("Case 1: ", len(audio_samples), "Start: ", start, "End: ", end)
        elif(end == self.ANIM_NUM_SAMPLES):
            audio_samples = audio_samples[start:]
            #print("Case 2: ", len(audio_samples), "Start: ", start, "End: ", end)
        else:
            audio_samples = audio_samples[start:end]
            #print("Case 3: ", len(audio_samples), "Start: ", start, "End: ", end)

        self.audioBuffer = audio_samples
        
        try:
            if(self.UI_PRESENT):
                self.line.set_ydata(self.audioBuffer)
                self.canvas.draw() #Redraws the canvas
                self.canvas.flush_events() #Flushes events
            else:
                # Update the plot efficiently
                self.line.set_ydata(self.audioBuffer)
                self.fig.canvas.draw()
                self.fig.canvas.flush_events()
                
        except ValueError:
            print("ValueError: audio_samples invalid.")

    def plotWaveform(self):
        if self.UI_PRESENT:
            if self.NumHarmonics==0:
                fig, ax = plt.subplots()
                ax.set_title("Base WaveForm Shape: Repeated at Note Freq.")
                ax.plot(self.WaveArray)
                ax.autoscale_view()

                #Remove x-axis and y-axis ticks and labels
                ax.set_xticks([])
                ax.set_yticks([])
                ax.set_ylabel("Ouput to DAC (Not Full Range)")
                ax.set_xlabel("Duration: Around 1-10 ms")

                canvas = FigureCanvasTkAgg(fig, master=self.ROOT_TK_WINDOW)
                canvas.draw()
                return canvas.get_tk_widget()
            else:
                fig, ax = plt.subplots()
                ax.set_title("Base WaveForm Shape: Repeated at Note Freq.")
                ax.plot(self.WaveArray,  label='Sum of Waveforms')
                
                ax.plot(self.harmonicArrays[0], label="Base Frequency")

                for i, harmonic in enumerate(self.harmonicArrays[1:]):
                    if i < 4:
                        text = "Harmonic " + str(i+1)
                        ax.plot(harmonic, label=text)
                    else:
                        ax.plot(harmonic)
                
                ax.autoscale_view()

                #Remove x-axis and y-axis ticks and labels 
                ax.set_xticks([])
                ax.set_yticks([])
                ax.set_ylabel("Ouput to DAC (Not Full Range)")
                ax.set_xlabel("Duration: Around 1-10 ms")
                ax.legend()
                canvas = FigureCanvasTkAgg(fig, master=self.ROOT_TK_WINDOW)
                canvas.draw()
                return canvas.get_tk_widget()
        
        else:
            x=[]
            for i in range(self.__WAVE_SAMPLES):
                x.append(i)
            plt.plot(x, self.WaveArray)
            plt.show()

    def genSinArray(self):
        """
        Generates an array of sin values for self.WaveArray.
        Values scaled with INIT_AMPLITUDE.
        Done with vectoriztion and numpy.
        """
        data = np.linspace(0, self.__WAVE_SAMPLES, self.__WAVE_SAMPLES).astype(np.float32)
        data = ((data/self.__WAVE_SAMPLES)*2*math.pi).astype(np.float32)
        return (self.__INIT_AMPLITUDE * np.sin(data)).astype(np.float32)

    def genSquareArray(self):
        """
        Generates an array of sin values for self.WaveArray.
        Values scaled with INIT_AMPLITUDE.
        """
        data=[]
        LowVal = round(0-(self.__INIT_AMPLITUDE/2))
        HighVal = round(self.__INIT_AMPLITUDE/2)
        quarter=round(self.__WAVE_SAMPLES/4)

        for i in range(self.__WAVE_SAMPLES):
            if i<quarter:
                data.append(LowVal)
            elif i < (quarter*2):
                data.append(HighVal)
            elif i < (quarter*3):
                data.append(HighVal)
            else:
                data.append(LowVal)
        
        return np.array(data, dtype=np.float32)
        
    
    def genTriArray(self):
        """
        Generates an array of sin values for self.WaveArray.
        Values scaled with INIT_AMPLITUDE.
        """
        LowVal = round(0-(self.__INIT_AMPLITUDE/2))
        HighVal = round(self.__INIT_AMPLITUDE/2)
        half = int(self.__WAVE_SAMPLES/2)
        quarter = int(self.__WAVE_SAMPLES/4)

        data1 = np.linspace(0, HighVal, quarter).astype(np.float32)
        data2 = np.linspace(HighVal, LowVal, half).astype(np.float32)
        data3 = np.linspace(LowVal, 0, quarter).astype(np.float32)
        data = np.concatenate((data1, data2, data3)).astype(np.float32)
        
        return data

    def genSawArray(self):
        """
        Generates an array of sin values for self.WaveArray.
        Values scaled with INIT_AMPLITUDE.
        """
        self.pauseStream()
        data=[]
        LowVal = round(0-(self.__INIT_AMPLITUDE/2))
        HighVal = round(self.__INIT_AMPLITUDE/2)
        half = int(self.__WAVE_SAMPLES/2)
        
        data1 = np.linspace(0, HighVal, half).astype(np.float32)
        data2 = np.linspace(LowVal, 0, half).astype(np.float32)
        
        data = np.concatenate((data1, data2)).astype(np.float32)
        # data = self.pad_with_zeros(data, self.__WAVE_SAMPLES)
        
        return data
    
    def genWaveArray(self):
        """
        Used in the generate functions to create an array of values.
        The WaveArray is stepped through to create the waveform.
        """
        tempWaveForm = np.zeros(self.__WAVE_SAMPLES, dtype=np.float32)
        
        if(self.__WAVEFORM == waveforms.sin):
            tempWaveForm = self.genSinArray()
        elif(self.__WAVEFORM == waveforms.tri):
            tempWaveForm = self.genTriArray()
        elif(self.__WAVEFORM == waveforms.square):
            tempWaveForm = self.genSquareArray()
        elif(self.__WAVEFORM == waveforms.saw):
            tempWaveForm = self.genSawArray()
        
        tempWaveForm = self.genHarmonics(self.NumHarmonics, tempWaveForm)
        
        tempWaveForm = np.clip(tempWaveForm, -2**15+1, 2**15-1).astype(np.float32)

        self.pauseStream()
        self.WaveArray = tempWaveForm
        self.continueStream()

    def genHarmonics(self, numHarmonics, data):
        self.harmonicArrays = []
        self.harmonicArrays.append(np.around(data).astype(np.int16))
        newData = np.copy(data)
        for i in range(numHarmonics):
            n = i+2
            partData = data[::n] / (n*2)
            #partData = (partData * harmonicsVol) #Higher harmonics are quieter
            partData = np.tile(partData, n)
            partData = partData[0:self.__WAVE_SAMPLES]
            self.harmonicArrays.append(np.around(partData).astype(np.int16))
            newData += partData #Higher harmonics are quieter

        if numHarmonics==0:
            newData = data

        return newData
    
    def setWaveForm(self, waveform):
        self.__INIT_AMPLITUDE = 16000
        self.__WAVE_SAMPLES = 2048

        self.__STEPS_PER_CYCLE = np.float32(self.__WAVE_SAMPLES / self.__SAMPLE_RATE)

        if(waveform=='sin'):
            self.__WAVEFORM = waveforms.sin
        elif(waveform=='tri'):
            self.__WAVEFORM = waveforms.tri
        elif(waveform=='square'):
            self.__WAVEFORM = waveforms.square
        elif(waveform=='saw'):
            self.__WAVEFORM = waveforms.saw
        elif(waveform=='other'):
            self.__WAVEFORM = waveforms.other
        else:
            self.__WAVEFORM = waveforms.zero
    
    
class NoteStates(Enum):
    """
    Used to control the different parts of the note.
    """
    NULL = -1
    OFF = 0
    ATTACK = 1
    ON = 2
    DECAY = 3

#Used to calculate the frequency using just intonation
justRatios = np.array([1, 16/15, 9/8, 6/5, 5/4, 4/3, 45/32, 3/2, 8/5, 5/3, 7/4, 15/8]).astype(np.float32)

#0 -10 octaves, one value for each octave. Lower notes sound quiter, higher notes sound louder
freqVolumeAdjust = [3.5, 3.5, 2.5, 1.8, 1.2, 1, 0.5, 0.4, 0.4, 0.3, 0.2]

# 0-10 octaves, one value for each octave. Lower notes need more frequency randomness to help synth sound more organic
freqRandomAdjust = [0.8, 0.8, 0.8, 0.6, 0.4, 0.3, 0.2, 0.1, 0, 0, 0]

class Note:
    """
    Used for initial calculations and storing values for each note.
    note.volume and note.frequency can either be a scalar, or a numpy array of size blocksize.
    """
    def __init__(self, pitch=0, volume=0, state=NoteStates.ATTACK, harmVol=0.2, randLvl=0, phase=0):
        if state==NoteStates.NULL:
            self.initNull()
        else:
            self.randLvl = randLvl #For detuning note
            self.state = state 
            self.pitch = pitch #Midi Pitch
            self.note = self.midi_note_to_name() 
            self.octave = self.pitch//12 #Gets octave for note
            self.init_frequency = np.float32(440 * 2**((pitch - 69) / 12) + self.randFreqAdjust())
            self.frequency = self.init_frequency #Converts midi note to frequency
            self.init_volume = volume*freqVolumeAdjust[self.octave] #Adjust volume based on freqeuncy
            self.volume = self.init_volume 
            self.phase_index=phase
            self.justFreqAdjust=0 
            self.profile_phase_index=0 #For controlling attack or release volume 

    def initNull(self):     
        self.state=NoteStates.NULL
        self.pitch = 0
        self.note = '0'
        self.init_frequency = 0
        self.frequency = 0
        self.init_volume = 0
        self.volume = 0
        self.phase_index=0
        self.profile_phase_index=0
        self.randomFreq = 0
        self.randLvl = 0

    def randFreqAdjust(self):
        maxRand = freqRandomAdjust[self.octave] #Adjusts randomness level based on octave
        return random.uniform(0, maxRand)*self.randLvl

    def setPhase(self, phase):
        self.phase_index = phase
        #print(self.phase_index)

    def setJustIntonation(self, rootFreq, rootPitch):
        """
        Generates frequency based on midi pitch, rootFreq (in 4th octave), and rootPitch (0-11).
        """
        interval = (self.pitch%12 - rootPitch)
        octave = (self.pitch-rootPitch)//12 - 5

        if octave == 0:
            octave = 1 
        elif octave < 0:
            octave=0.5**abs(octave)
        else:
            octave=2**octave

        self.init_frequency = np.float32((rootFreq* justRatios[interval]*octave) + self.randFreqAdjust())

    def midi_note_to_name(self):
        """
        Converts a MIDI note pitch to a note name (e.g., C4, G#3).
        """
        if(self.state == NoteStates.NULL):
            return '0'
        notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        octave = (self.pitch // 12) - 1
        note_index = self.pitch % 12
        return notes[note_index] + str(octave)
    
