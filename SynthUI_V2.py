import tkinter as tk
from ComplexSynthV6 import SynthGenerator

class SynthUI:
    def __init__(self):
        self.lightColor='#f0f7f4'
        self.darkColor= '#2374ab'
        self.root = tk.Tk()
        self.root.geometry("1350x1000")
        self.root.protocol("WM_DELETE_WINDOW", self.onClosing) 
        self.root.configure(background=self.lightColor)
        self.root.option_add("*Font", ("Arial", 16)) #Applies to all widgets
        self.root.title("Simple Synthesizer") 
        self.padSize = 15 
        self.justRoot = 0 
        self.notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

        # Set default colors for all labels
        self.root.option_add("*Foreground", self.lightColor)
        self.root.option_add("*Background", self.darkColor)

        # Configure row and column weights
        for i in range(7):
            self.root.rowconfigure(i, weight=1) 
        for i in range(6):
            self.root.columnconfigure(i, weight=1)  

        #Initialize synthesixer
        self.synthGen = SynthGenerator('sin', self.root)
        self.synthGen.startStream()

        self.noteLabel = tk.Label(self.root, text=self.synthGen.getNotes(), font=("Arial", 14))
        self.noteLabel.grid(row=0, column=0, columnspan=2,
                           padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)

        empty_label1 = tk.Label(self.root, text="Synth runs at 48 kHz sample rate\n  with 16 bit resolution.", font=('Arial', 14))
        empty_label1.grid(row=0, column=2, 
                          padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)
        
        self.initSlidersBtns()

        self.audioAnimInit()
        #Create Initial Waveform Plot
        self.updateWaveProfile()

    def run(self):
        self.root.mainloop()

    def onClosing(self):
        self.stopAudioAnim()
        self.synthGen.stopStream()
        exit()
    
    def initSlidersBtns(self):
        #Harmonic slider
        self.harmonicSlider = tk.Scale(self.root, from_=10, to=0, 
                                  orient=tk.HORIZONTAL, label="Num Harmonics", command=lambda x: self.harmSliderCall())
        self.harmonicSlider.set(0)
        self.harmonicSlider.grid(row=0, column=3, columnspan=1, 
                                padx=(2, 2), pady=(2, 2), sticky=tk.NSEW)
        
        #Harmonic volume
        self.harmVolSlider = tk.Scale(self.root, from_=10, to=0, 
                                  orient=tk.HORIZONTAL, label="Harmonic Volume", command=lambda x: self.harmVolSliderCall())
        self.harmVolSlider.set(2)
        self.harmVolSlider.grid(row=0, column=4, columnspan=1, 
                                padx=(2, 2), pady=(2, 2), sticky=tk.NSEW)

        #Set up volume slider
        self.volSlider = tk.Scale(self.root, from_=100, to=0, 
                                  orient=tk.VERTICAL, label="Volume", command=lambda x: self.volSliderCall())
        self.volSlider.set(40)
        self.volSlider.grid(row=1, column=1, rowspan=2, 
                            padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)

        #Set up wobble slider
        self.wobbleSlider = tk.Scale(self.root, from_= 60, to=5, 
                                    orient=tk.VERTICAL, label="Wobble", command=lambda x: self.wobbleSliderCall())
        self.wobbleSlider.set(15)
        self.wobbleSlider.grid(row=1, column=0, rowspan=2,
                               padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)

        #Create 4 Buttons for waveforms
        self.sinButton = tk.Button(self.root, text="Sine", command=self.sinBtnClick)
        self.sinButton.grid(row=3, column=0, 
                            padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)

        self.triButton = tk.Button(self.root, text="Triangle", command=self.triBtnClick)
        self.triButton.grid(row=3, column=1, 
                            padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)

        self.sawButton = tk.Button(self.root, text="Sawtooth", command=self.sawBtnClick)
        self.sawButton.grid(row=4, column=0, padx=(self.padSize, self.padSize), 
                            pady=(self.padSize, self.padSize), sticky=tk.NSEW)

        self.squareButton = tk.Button(self.root, text="Square", command=self.squareBtnClick)
        self.squareButton.grid(row=4, column=1, 
                               padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)

        #Set attack slider
        self.attackSlider = tk.Scale(self.root, from_=1, to=100, 
                                  orient=tk.HORIZONTAL, label="Attack", command=lambda x: self.attackSliderCall())
        self.attackSlider.set(5)
        self.attackSlider.grid(row=5, column=0, columnspan=2, 
                            padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)

        #Set decay slider
        self.decaySlider = tk.Scale(self.root, from_= 1, to=100, 
                                    orient=tk.HORIZONTAL, label="Decay", command=lambda x: self.decaySliderCall())
        self.decaySlider.set(10)
        self.decaySlider.grid(row=6, column=0, columnspan=2,
                               padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)

        #Set Just Intonation
        self.justToneButton = tk.Button(self.root, text=" Just\nIntonation", command=self.justToneCall)
        self.justToneButton.grid(row=0, column=5, rowspan=2,
                               padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)

        #Set note slider
        self.justNoteSlider = tk.Scale(self.root, from_= 0, to=len(self.notes)-1, 
                                    orient=tk.VERTICAL, showvalue=False, label="Just Root", command=lambda x: self.justNoteSliderCall())
        self.justNoteSlider.set(0)
        self.justNoteSlider.grid(row=3, column=5, 
                               padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)
        
        self.JustRootText = tk.Label(self.root, text=f"Off.\nJust Root\nNote: C", font=('Arial', 14))
        self.JustRootText.grid(row=2, column=5,
                               padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)
        
        #RandLvl 
        self.randLvlSlider = tk.Scale(self.root, from_= 0, to=100, 
                                    orient=tk.VERTICAL, label="Random Lvl", command=lambda x: self.randLvlSliderCall())
        self.randLvlSlider.set(0)
        self.randLvlSlider.grid(row=4, column=5, rowspan=2,
                               padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW) 

        #Phase Offset
        self.phaseLvlSlider = tk.Scale(self.root, from_= 0, to=100, 
                                    orient=tk.VERTICAL, label="Phase Lvl", command=lambda x: self.phaseLvlSliderCall())
        self.phaseLvlSlider.set(0)
        self.phaseLvlSlider.grid(row=6, column=5, 
                               padx=(self.padSize, self.padSize), pady=(self.padSize, self.padSize), sticky=tk.NSEW)        


    def updateWaveProfile(self):
        element = self.synthGen.plotWaveform()
        element.grid(row=4, column=2, rowspan=3, columnspan=3, sticky=tk.NSEW)

    def audioAnimInit(self):
        #Start audio anim plot
        self.synthAudioAnim = self.synthGen.initAnim()
        self.synthAudioAnim.grid(row=1, column=2, rowspan=3, columnspan=3, sticky=tk.NSEW)
        self.audioAfterID = self.root.after(100, self.updateAdioAnim)

    def updateAdioAnim(self):
        try:
            self.synthGen.animSoundUpdate()
        except Exception as e:
            print("Failed to load real time audio.")
        self.noteLabel.config(text=self.synthGen.getNotes())
        self.audioAfterID = self.root.after(100, self.updateAdioAnim)

    def stopAudioAnim(self):
        if self.audioAfterID is not None:
            self.root.after_cancel(self.audioAfterID)
            self.audioAfterID  = None
    
    def volSliderCall(self):
        self.synthGen.setVolume(self.volSlider.get()/200)
    
    def wobbleSliderCall(self):
        self.synthGen.setWobble(self.wobbleSlider.get())
    
    def sinBtnClick(self):
        self.synthGen.setWaveForm('sin')
        self.synthGen.genWaveArray()
        self.updateWaveProfile()
    
    def triBtnClick(self):
        self.synthGen.setWaveForm('tri')
        self.synthGen.genWaveArray()
        self.updateWaveProfile()
    
    def sawBtnClick(self):
        self.synthGen.setWaveForm('saw')
        self.synthGen.genWaveArray()
        self.updateWaveProfile()
    
    def squareBtnClick(self):
        self.synthGen.setWaveForm('square')
        self.synthGen.genWaveArray()
        self.updateWaveProfile()

    def attackSliderCall(self):
        try:
            self.synthGen.setAdsr(self.attackSlider.get(), self.decaySlider.get())
        except Exception as e:
            print("Failed")

    def decaySliderCall(self):
        try:
            self.synthGen.setAdsr(self.attackSlider.get(), self.decaySlider.get())
        except Exception as e:
            print("Failed")
    
    def harmSliderCall(self):
        self.synthGen.NumHarmonics = self.harmonicSlider.get()
        self.synthGen.genWaveArray()
        self.updateWaveProfile()
    
    def harmVolSliderCall(self):
        self.synthGen.harmonicsVol = (self.harmVolSlider.get()/10)
    
    def justToneCall(self):
        self.synthGen.justIntonation = not self.synthGen.justIntonation
        self.synthGen.setJustRoot(self.justRoot)
        note = self.notes[self.justRoot]
        if self.synthGen.justIntonation:
            self.JustRootText.config(text=f"On.\nJust Root\nNote: {note}")
        else:
            self.JustRootText.config(text=f"Off.\nJust Root\nNote:  {note}")
    
    def justNoteSliderCall(self):
        self.justRoot = self.justNoteSlider.get()
        self.synthGen.setJustRoot(self.justRoot)
        note = self.notes[self.justRoot]
        if self.synthGen.justIntonation:
            self.JustRootText.config(text=f"On.\nJust Root Note:\n {note}")
        else:
            self.JustRootText.config(text=f"Off.\nJust Root\nNote: {note}")
    
    def randLvlSliderCall(self):
        lvl = self.randLvlSlider.get()
        if lvl < 50:
            self.synthGen.randLvl = lvl/5
        else:
            self.synthGen.randLvl = lvl*2
    
    def phaseLvlSliderCall(self):
        lvl = self.phaseLvlSlider.get()/100
        self.synthGen.phaseLvl = lvl


synth = SynthUI()
try:
    synth.run()

except KeyboardInterrupt:
    None



    

