import numpy as np
import matplotlib.pyplot as plt

WAVE_SAMPLES = 2048
INIT_AMPLITUDE = 16000
BLOCKSIZE = 512
SAMPLE_RATE = 48000
STEPS_PER_CYCLE = np.float32(WAVE_SAMPLES / SAMPLE_RATE)
VOLUME = 0.5
NUMBLOCKS = 5

def genSinArray():
    """
    Generates an array of sin values for .WaveArray.
    Values scaled with INIT_AMPLITUDE.
    Done with vectoriztion and numpy.
    """
    data = np.linspace(0, WAVE_SAMPLES, WAVE_SAMPLES).astype(np.float32)
    data = ((data/WAVE_SAMPLES)*2*np.pi).astype(np.float32)
    return (INIT_AMPLITUDE * np.sin(data)).astype(np.float32)

waveArray = genSinArray()

def genSoundData(note):
    """
    Collects 32 (2 byte) samples from the wave array. 
    Adjusts each sample for volume and rounds.
    Sound Generation is done by gathering samples from an a large sample array of the current waveform.
    Done using vectorization for speed.
    """
    note.frequency = note.init_frequency

    #STEPS_PER_CYCLE = np.float32(WAVE_SAMPLES/ SAMPLE_RATE)
    #Incriments through waveform array, inriments with floats to make frequencies more accurate
    phase_increment = note.frequency * STEPS_PER_CYCLE
    end = (note.phase_index + phase_increment * (BLOCKSIZE)) #Always generate more phases then needed
    
    # 1. Create an array of phase indices:
    phases = np.arange(note.phase_index, end, phase_increment)
    
    phases = phases[:512] #Limit the number of phases to the correct amount
    
    phases = np.round(phases).astype(np.uint16) #Phases are calculated using a float, then round, helps with frequency accuracy

    # 2. Wrap the phase indices using the modulo operator (vectorized):
    phases %= WAVE_SAMPLES
    
    #3. Store the last phase index for the next block
    note.phase_index = (phases[-1]+phase_increment) % WAVE_SAMPLES
    
    # 4. Use the phase indices to index into the wavetable (vectorized):
    #The note.volume can be scaler or an array of 512 values, depending on what state the note is in.
    soundData = np.around(waveArray[phases] * note.volume * VOLUME).astype(np.float32)
    
    return soundData

#Used to calculate the frequency using just intonation
justRatios = np.array([1, 16/15, 9/8, 6/5, 5/4, 4/3, 45/32, 3/2, 8/5, 5/3, 7/4, 15/8]).astype(np.float32)
#0 -10 octaves, one value for each octave. Lower notes sound quiter, higher notes sound louder
freqVolumeAdjust = [3.5, 3.5, 2.5, 1.8, 1.2, 1, 0.5, 0.4, 0.4, 0.3, 0.2]

class Note:
    """
    Used for initial calculations and storing values for each note.
    note.volume and note.frequency can either be a scalar, or a numpy array of size blocksize.
    """
    def __init__(self, pitch=0, volume=0.5, phase=0):
        self.pitch = pitch #Midi Pitch
        self.note = self.midi_note_to_name() 
        self.octave = self.pitch//12 #Gets octave for note
        self.init_frequency = np.float32(440 * 2**((pitch - 69) / 12))
        self.frequency = self.init_frequency #Converts midi note to frequency
        self.init_volume = volume*freqVolumeAdjust[self.octave] #Adjust volume based on freqeuncy
        self.volume = self.init_volume 
        self.phase_index=phase
        self.justFreqAdjust=0 
        self.profile_phase_index=0 #For controlling attack or release volume 

    def setPhase(self, phase):
        self.phase_index = phase
        print(self.phase_index)

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

        self.init_frequency = np.float32((rootFreq* justRatios[interval]*octave))

    def midi_note_to_name(self):
        """
        Converts a MIDI note pitch to a note name (e.g., C4, G#3).
        """
        notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        octave = (self.pitch // 12) - 1
        note_index = self.pitch % 12
        return notes[note_index] + str(octave)


def genData(notes):
    outputData = np.array([]).astype(np.int16)

    for i in range(NUMBLOCKS):
        #Set 512 samples to be zero
        data = np.zeros(BLOCKSIZE).astype(np.float32)

        #Generate 512 samples for each note
        for note in notes:
            data += genSoundData(note) 
        
        data = np.clip(data, -2**15+1, 2**15-1).astype(np.int16)

        outputData = np.concatenate((outputData, data)).astype(np.int16)
    
    return outputData

startPhase = 0
notes = [Note(48, phase=0), Note(52, phase=startPhase), Note(55, phase=startPhase)]#, Note(59, phase=startPhase)]

for note in notes:
    note.setJustIntonation(440 * 2**((60 - 69) / 12), 0) #Set just intonation for middle C

outputData = genData(notes)

numPts = len(outputData)
x = np.linspace(0, numPts, numPts)
plt.plot(x, outputData)
plt.show()


#Tried to average out phases, had noe effect
# outputData = np.zeros(BLOCKSIZE*NUMBLOCKS).astype(np.int16)

# numPhases = 100

# for i in range(0, numPhases):
#     startPhase =i
#     notes = [Note(48, phase=0), Note(52, phase=startPhase), Note(55, phase=startPhase)]#, Note(59, phase=startPhase)]

#     for note in notes:
#         note.setJustIntonation(440 * 2**((60 - 69) / 12), 0) #Set just intonation for middle C

#     data = np.around(genData(notes) / numPhases).astype(np.int16)

#     outputData += data