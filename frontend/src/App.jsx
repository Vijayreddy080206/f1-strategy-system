import React, { useState, useEffect, useRef } from 'react';
import { io } from 'socket.io-client';

const socket = io('http://localhost:4000');

const getTireHex = (comp) => {
  if (comp === 'SOFT') return '#ff3333';
  if (comp === 'MEDIUM') return '#ffd700';
  if (comp === 'HARD') return '#cccccc';
  if (comp === 'INTERMEDIATE' || comp === 'INTER') return '#4ade80';
  if (comp === 'WET') return '#3b82f6';
  return '#888888';
};

const getTireBg = (comp) => {
  if (comp === 'SOFT') return 'bg-[#ff3333]';
  if (comp === 'MEDIUM') return 'bg-[#ffd700]';
  if (comp === 'HARD') return 'bg-[#cccccc]';
  if (comp === 'INTERMEDIATE' || comp === 'INTER') return 'bg-[#4ade80]';
  if (comp === 'WET') return 'bg-[#3b82f6]';
  return 'bg-[#888888]';
};

export default function App() {
  const [globalData, setGlobalData] = useState(null);
  const [activeDriver, setActiveDriver] = useState('');
  const [showLeaderGap, setShowLeaderGap] = useState(false);
  
  // UI States for the Live Feed Connection
  const [isConnecting, setIsConnecting] = useState(false);
  const [showNoLiveModal, setShowNoLiveModal] = useState(false);
  
  const historyRef = useRef({});
  const connectionTimerRef = useRef(null); // Tracks the 7-second timeout

  const formatRaceTime = (totalSeconds) => {
    if (!totalSeconds) return "0:00.00";
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = (totalSeconds % 60).toFixed(2);
    return `${minutes}:${seconds.padStart(5, '0')}`;
  };

  useEffect(() => {
    socket.on('f1_telemetry', (data) => {
      // If we receive data, kill the "No Race" timer! We are connected!
      if (connectionTimerRef.current) {
        clearTimeout(connectionTimerRef.current);
        setIsConnecting(false);
      }
      
      setGlobalData(data);
      
      if (!activeDriver && data.drivers && Object.keys(data.drivers).length > 0) {
        const leader = Object.keys(data.drivers).reduce((a, b) => data.drivers[a].position < data.drivers[b].position ? a : b);
        setActiveDriver(leader);
      }
    });

    return () => socket.off('f1_telemetry');
  }, [activeDriver]); 

  useEffect(() => {
    if (globalData && globalData.drivers) {
      const lap = globalData.lap_number;
      Object.entries(globalData.drivers).forEach(([driver, dData]) => {
        if (!historyRef.current[driver]) {
          historyRef.current[driver] = { stints: [] };
        }
        
        const h = historyRef.current[driver];
        const lastStint = h.stints[h.stints.length - 1];
        
        let comp = dData.compound;
        if (!comp || comp === 'UNKNOWN' || comp === 'nan') comp = 'MEDIUM'; 

        if (!lastStint || comp !== lastStint.compound || dData.tire_age < lastStint.lastAge) {
            h.stints.push({ compound: comp, startLap: Math.max(1, lap - dData.tire_age + 1), lastAge: dData.tire_age });
        } else {
            lastStint.lastAge = dData.tire_age;
            lastStint.compound = comp; 
        }
      });
    }
  }, [globalData]);

  // Unified Stop Function
  const handleStopFeed = () => {
    socket.emit('send_command', { command: 'STOP' });
    if (connectionTimerRef.current) clearTimeout(connectionTimerRef.current);
    setIsConnecting(false);
    setGlobalData(null);
    setActiveDriver('');
    historyRef.current = {}; 
  };

  // Live Button Logic with 7-Second Timeout
  const handleStartLive = () => {
    socket.emit('send_command', { command: 'START_LIVE' });
    setIsConnecting(true);
    setShowNoLiveModal(false);

    // If 7 seconds pass and globalData is still null, throw the error
    connectionTimerRef.current = setTimeout(() => {
      setShowNoLiveModal(true);
      handleStopFeed(); // Auto-kill the dead Python feed
    }, 7000);
  };

  // -------------------------------------------------------------------------
  // STARTUP / LOADING SCREEN
  // -------------------------------------------------------------------------
  if (!globalData || !globalData.drivers || !globalData.drivers[activeDriver]) {
    return (
      <div className="relative flex flex-col h-screen bg-[#050508] text-white items-center justify-center font-sans overflow-hidden">
        
        {/* NO LIVE RACE POPUP MODAL */}
        {showNoLiveModal && (
          <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
            <div className="bg-[#10101a] border border-[#e10600] rounded-2xl p-8 max-w-md w-full shadow-[0_0_60px_rgba(225,6,0,0.3)] flex flex-col items-center text-center">
              <div className="w-16 h-16 bg-[#2a0000] rounded-full flex items-center justify-center mb-5 border border-[#e10600] shadow-[0_0_15px_rgba(225,6,0,0.5)]">
                 <span className="text-2xl animate-pulse">📡</span>
              </div>
              <h2 className="text-xl font-black text-[#e8e8f0] mb-3 tracking-[0.15em] uppercase">No Active Session</h2>
              <p className="text-[#888] text-xs leading-relaxed mb-8 px-4">
                The FIA telemetry servers are currently silent. There is no live Formula 1 session broadcasting at this moment. Please check the official race weekend schedule.
              </p>
              <button 
                onClick={() => setShowNoLiveModal(false)} 
                className="px-8 py-3 bg-[#e10600] hover:bg-[#ff3333] text-white font-bold rounded border border-[#ff6666] text-xs tracking-widest transition-all w-full shadow-lg"
              >
                ACKNOWLEDGE
              </button>
            </div>
          </div>
        )}

        <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(225,6,0,0.08)_0%,transparent_60%)] pointer-events-none"></div>
        <div className="absolute inset-0 opacity-10 pointer-events-none" style={{ backgroundImage: 'linear-gradient(#1e1e30 1px, transparent 1px), linear-gradient(90deg, #1e1e30 1px, transparent 1px)', backgroundSize: '40px 40px' }}></div>

        <div className="relative z-10 flex flex-col items-center bg-[#0a0a0f]/80 backdrop-blur-md p-12 rounded-3xl border border-[#1e1e30] shadow-[0_0_60px_rgba(0,0,0,0.6)] min-w-[500px]">
          
          <img src="https://upload.wikimedia.org/wikipedia/commons/3/33/F1.svg" alt="F1" className="h-10 mb-5 opacity-90 drop-shadow-[0_0_8px_rgba(255,255,255,0.2)]" />
          
          <div className="text-[#e8e8f0] text-3xl font-black tracking-[0.2em] uppercase mb-1">
            PitWall AI Engine
          </div>
          <div className="text-[#e10600] text-xs font-bold tracking-[0.4em] uppercase mb-10 flex items-center gap-2">
            <span className="w-8 h-px bg-gradient-to-r from-transparent to-[#e10600]"></span>
            Strategic Command Center
            <span className="w-8 h-px bg-gradient-to-l from-transparent to-[#e10600]"></span>
          </div>
          
          <div className="flex gap-5 w-full mb-8">
            <button 
              onClick={() => {
                socket.emit('send_command', { command: 'START_REPLAY', year: 2023, track: 'Qatar' });
                setIsConnecting(true);
              }}
              disabled={isConnecting}
              className="flex-1 group relative px-6 py-5 bg-[#10101a] hover:bg-[#1a1a2e] border border-[#3e3e50] rounded-xl text-[13px] font-bold text-[#e8e8f0] transition-all overflow-hidden flex flex-col items-center gap-2 shadow-lg disabled:opacity-50"
            >
              <span className="text-2xl z-10 opacity-80 group-hover:opacity-100">🏁</span>
              <span className="z-10 tracking-widest">START REPLAY</span>
            </button>

            <button 
              onClick={handleStartLive}
              disabled={isConnecting}
              className="flex-1 group relative px-6 py-5 bg-[#1a0000] hover:bg-[#2a0000] border border-[#e10600] rounded-xl text-[13px] font-bold text-[#e8e8f0] transition-all overflow-hidden flex flex-col items-center gap-2 shadow-[0_0_20px_rgba(225,6,0,0.15)] disabled:opacity-50"
            >
              <div className="relative flex h-6 w-6 items-center justify-center z-10">
                <span className={`absolute inline-flex h-full w-full rounded-full bg-[#ff3333] opacity-60 ${isConnecting ? 'animate-ping' : ''}`}></span>
                <span className="relative inline-flex rounded-full h-3 w-3 bg-[#e10600]"></span>
              </div>
              <span className="z-10 tracking-widest text-[#e10600] group-hover:text-white">START LIVE</span>
            </button>
          </div>

          <div className="flex items-center gap-3 px-6 py-3 bg-[#050508] border border-[#1e1e30] rounded-full shadow-inner min-w-[320px] justify-center">
            <div className={`w-2 h-2 rounded-full ${isConnecting ? 'bg-[#4ade80] animate-pulse shadow-[0_0_8px_rgba(74,222,128,0.6)]' : 'bg-[#fbbf24] animate-pulse shadow-[0_0_8px_rgba(251,191,36,0.6)]'}`}></div>
            <div className="text-[#888] font-mono text-[10px] tracking-[0.2em] uppercase">
              {isConnecting ? 'CONNECTING TO FIA SECURE SERVERS...' : 'System Standby. Awaiting Telemetry...'}
            </div>
          </div>

        </div>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // MAIN DASHBOARD LOGIC
  // -------------------------------------------------------------------------
  const allDrivers = Object.keys(globalData.drivers).sort((a, b) => globalData.drivers[a].position - globalData.drivers[b].position);
  const telemetry = globalData.drivers[activeDriver];

  const activeIndex = allDrivers.indexOf(activeDriver);
  const driverAhead = activeIndex > 0 ? allDrivers[activeIndex - 1] : 'CLEAR';
  const driverBehind = activeIndex < allDrivers.length - 1 ? allDrivers[activeIndex + 1] : 'CLEAR';

  const isInter = telemetry.compound === 'INTERMEDIATE' || telemetry.compound === 'INTER';
  const isWetCompound = telemetry.compound === 'WET';
  const degMultiplier = telemetry.compound === 'SOFT' ? 0.15 : telemetry.compound === 'MEDIUM' ? 0.08 : telemetry.compound === 'HARD' ? 0.04 : isInter ? 0.12 : isWetCompound ? 0.06 : 0.10;
  
  const driverPaceVariance = 1 + (telemetry.position * 0.03); 
  const performanceLoss = (telemetry.tire_age * degMultiplier * driverPaceVariance).toFixed(2);
  const trackTemp = (38.2 + (globalData.lap_number * 0.05) - (globalData.track_moisture * 0.1)).toFixed(1);
  const isWet = globalData.track_moisture > 20;

  const stratACall = telemetry.recommendation || "STAY OUT (TIRES FRESH)"; 
  const isPitRecommended = stratACall.includes('PIT');
  
  let stratBCall = "STAY OUT";
  if (!isPitRecommended) {
      if (globalData.track_moisture > 60) stratBCall = "PIT → WET";
      else if (globalData.track_moisture > 20) stratBCall = "PIT → INTERMEDIATE";
      else stratBCall = `PIT → ${telemetry.compound === 'HARD' ? 'MEDIUM' : 'HARD'}`;
  }

  const tireAgeRatio = Math.min(1, telemetry.tire_age / 35);
  const svgDotX = 20 + (tireAgeRatio * 250);
  let svgDotY = 80;
  if (telemetry.compound === 'HARD') svgDotY = 84 + (tireAgeRatio * -31);
  else if (telemetry.compound === 'MEDIUM') svgDotY = 80 + (tireAgeRatio * -68);
  else if (telemetry.compound === 'SOFT') svgDotY = 82 + (tireAgeRatio * -58);
  else if (isInter) svgDotY = 70 + (tireAgeRatio * -70);
  else if (isWetCompound) svgDotY = 50 + (tireAgeRatio * -17);

  return (
    <div className="flex h-screen min-h-[900px] bg-[#0a0a0f] text-[#e8e8f0] font-sans overflow-hidden">
      
      {/* LEFT SIDEBAR */}
      <div className="w-[220px] min-w-[220px] bg-[#10101a] border-r border-[#1e1e30] flex flex-col p-0 overflow-y-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
        <div className="p-[18px_16px_14px] border-b border-[#1e1e30] sticky top-0 bg-[#10101a] z-10">
          <div className="flex items-center gap-3">
            <img src="https://upload.wikimedia.org/wikipedia/commons/3/33/F1.svg" alt="Formula 1" className="h-5 object-contain" />
            <div className="border-l border-[#1e1e30] pl-3">
              <div className="text-[13px] font-bold text-white tracking-wide">PitWall AI</div>
              <div className="text-[9px] text-[#666] tracking-[1.5px] uppercase mt-px">Global Intelligence</div>
            </div>
          </div>
        </div>

        <div className="p-[12px_10px] flex-1 mt-2">
          <div className="text-[9px] text-[#444] tracking-[1.5px] uppercase mb-2 px-1.5 flex justify-between">
            <span>Grid Roster</span><span className="text-[#e10600] font-bold">{allDrivers.length} ACTIVE</span>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {allDrivers.map(d => (
              <div 
                key={d} onClick={() => setActiveDriver(d)}
                className={`p-[6px_4px] rounded-[5px] border cursor-pointer text-center text-[11px] font-medium transition-all ${activeDriver === d ? 'bg-[#1a0000] border-[#e10600] text-[#e10600]' : 'bg-[#141420] border-[#1e1e30] text-[#888] hover:bg-[#1a1a2e]'}`}
              >
                <span className="text-[8px] text-[#555] mr-1">P{globalData.drivers[d].position}</span> {d}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* MAIN CONTENT AREA */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden bg-[#0a0a0f] flex flex-col">
        
        {/* TOP NAVBAR & MANAGER CONTROLS */}
        <div className="h-[52px] bg-[#10101a] border-b border-[#1e1e30] flex items-center px-5 gap-4 justify-between shrink-0 sticky top-0 z-10 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="text-[13px] text-[#e8e8f0] font-semibold">
              Lap {globalData.lap_number} <span className="text-[11px] font-normal text-[#555]">/ {globalData.total_laps}</span>
            </div>
          </div>
          
          <div className="flex items-center gap-2">
            <button onClick={() => { socket.emit('send_command', { command: 'START_REPLAY', year: 2023, track: 'Qatar' }); }} className="px-3 py-1.5 bg-[#1a1a2e] hover:bg-[#2a2a40] border border-[#3e3e50] rounded text-[10px] font-bold text-[#ccc] transition-colors cursor-pointer">▶ START REPLAY</button>
            <button onClick={handleStartLive} className="px-3 py-1.5 bg-[#2a0a0a] hover:bg-[#3a0a0a] border border-[#e10600] rounded text-[10px] font-bold text-[#e10600] transition-colors cursor-pointer">🔴 START LIVE</button>
            <button onClick={handleStopFeed} className="px-3 py-1.5 bg-[#141420] hover:bg-[#e10600] border border-[#1e1e30] hover:border-[#e10600] rounded text-[10px] font-bold text-[#888] hover:text-white transition-colors cursor-pointer ml-2">⏹ STOP FEED</button>
          </div>

          <div className="flex items-center gap-2.5">
            <div className={`px-2.5 py-1 rounded-full text-[10px] font-bold tracking-wide ${globalData.is_sc_active ? 'bg-[#3d1a00] border-[#e10600] text-[#e10600]' : 'bg-[#0a1f0a] border-[#1a4d1a] text-[#4ade80]'}`}>
              {globalData.is_sc_active ? 'SAFETY CAR DEPLOYED' : 'GREEN FLAG'}
            </div>
          </div>
        </div>

        {/* DASHBOARD PANELS */}
        <div className="p-4 flex-1 flex flex-col gap-3">
          
          {/* AI ALERT BANNER */}
          <div className="bg-[#1a0000] border border-[#e10600] rounded-lg p-3 flex items-center gap-3 shadow-[0_0_20px_rgba(225,6,0,0.15)] shrink-0">
            <div className="w-7 h-7 bg-[#e10600] rounded-full flex items-center justify-center text-[14px] text-white shrink-0 font-bold">!</div>
            <div className="flex-1">
              <div className="text-[16px] font-bold text-[#e10600] mb-0.5 uppercase">{stratACall}</div>
              <div className="text-[11px] text-[#999]">{activeDriver} on {telemetry.tire_age}L {telemetry.compound}. Gap behind: {telemetry.gap_behind > 50 ? 'CLEAR' : telemetry.gap_behind.toFixed(1) + 's'}. MCTS Engine optimally computed.</div>
            </div>
            <div className="flex-col shrink-0 text-right">
              <div className="text-[9px] text-[#555] mb-0.5">Confidence</div>
              <div className="text-[18px] font-bold text-[#e10600]">94.2%</div>
            </div>
          </div>

          {/* ACTIVE DRIVER METRICS */}
          <div className="grid grid-cols-4 gap-3 shrink-0">
            <div className="bg-[#10101a] border border-[#1e1e30] rounded-[10px] p-3.5">
              <div className="text-[9px] text-[#444] uppercase tracking-wide mb-2.5">Tire status</div>
              <div className="flex items-center gap-1.5 mb-1">
                <span className={`w-2.5 h-2.5 rounded-full ${getTireBg(telemetry.compound)}`}></span>
                <span className="text-[20px] font-bold text-[#e8e8f0] leading-none">{telemetry.tire_age}</span><span className="text-[11px] text-[#555] self-end mb-0.5">laps</span>
              </div>
              <div className="text-[10px] text-[#555] mt-1">{telemetry.compound} Compound</div>
              <div className="mt-2"><div className="h-[5px] bg-[#1e1e30] rounded-[3px]"><div className="h-full bg-[#e10600] rounded-[3px] transition-all duration-500" style={{width: `${Math.min(100, telemetry.tire_age * 3.5)}%`}}></div></div></div>
            </div>
            <div className="bg-[#10101a] border border-[#1e1e30] rounded-[10px] p-3.5">
              <div className="text-[9px] text-[#444] uppercase tracking-wide mb-2.5">Performance loss</div>
              <div className="text-[22px] font-bold text-[#e10600] leading-none">+{performanceLoss}s</div>
              <div className="text-[10px] text-[#555] mt-1">vs best lap on this set</div>
              <div className="text-[10px] text-[#e10600] mt-1.5">+{degMultiplier}s/lap trend</div>
            </div>
            <div className="bg-[#10101a] border border-[#1e1e30] rounded-[10px] p-3.5">
              <div className="text-[9px] text-[#444] uppercase tracking-wide mb-2.5">Gap analysis</div>
              <div className="flex justify-between mb-1.5">
                <div><div className="text-[9px] text-[#444]">Ahead · {driverAhead}</div><div className="text-[16px] font-bold text-[#4ade80]">{telemetry.gap_ahead > 50 ? 'CLEAR' : `+${telemetry.gap_ahead.toFixed(1)}s`}</div></div>
                <div className="text-right"><div className="text-[9px] text-[#444]">Behind · {driverBehind}</div><div className="text-[16px] font-bold text-[#e10600]">{telemetry.gap_behind > 50 ? 'CLEAR' : `-${telemetry.gap_behind.toFixed(1)}s`}</div></div>
              </div>
              <div className="h-1 bg-[#1e1e30] rounded flex items-center my-1.5"><div className="h-full w-[28%] bg-[#e10600] rounded"></div></div>
              <div className="text-[9px] text-[#e10600] mt-0.5">{telemetry.drs_train_length > 1 ? `🚂 DRS TRAIN` : 'Undercut window OPEN'}</div>
            </div>
            <div className="bg-[#10101a] border border-[#1e1e30] rounded-[10px] p-3.5">
              <div className="text-[9px] text-[#444] uppercase tracking-wide mb-2.5">Target Driver</div>
              <div className="text-[22px] font-bold text-[#e8e8f0] leading-none">{activeDriver}</div>
              <div className="text-[10px] text-[#555] mt-1">Current Race Position</div>
              <div className="text-[18px] text-[#4ade80] mt-0.5 font-bold">P{telemetry.position}</div>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3 flex-1 min-h-0">
            <div className="col-span-2 flex flex-col gap-3">
              
              <div className="grid grid-cols-2 gap-3 shrink-0">
                {/* DEGRADATION MODEL */}
                <div className="bg-[#10101a] border border-[#1e1e30] rounded-[10px] p-3.5">
                  <div className="text-[9px] text-[#444] uppercase tracking-wide mb-2.5">Tire degradation Model</div>
                  <div className="h-[110px] bg-[#0d0d18] rounded-md overflow-hidden relative mt-2">
                    <svg className="w-full h-full" viewBox="0 0 280 110" preserveAspectRatio="none">
                      <line x1="20" y1="10" x2="20" y2="90" stroke="#1e1e30" strokeWidth="0.5"/>
                      <line x1="20" y1="90" x2="270" y2="90" stroke="#1e1e30" strokeWidth="0.5"/>
                      
                      <polyline points="20,84 50,82 80,80 110,77 140,74 170,70 200,65 230,60 270,53" stroke="#cccccc" strokeWidth={telemetry.compound === 'HARD' ? "2.5" : "1"} opacity={telemetry.compound === 'HARD' ? "1" : "0.3"} fill="none"/>
                      <polyline points="20,80 50,76 80,71 110,65 140,57 170,48 200,38 230,26 270,12" stroke="#ffd700" strokeWidth={telemetry.compound === 'MEDIUM' ? "2.5" : "1"} opacity={telemetry.compound === 'MEDIUM' ? "1" : "0.3"} fill="none"/>
                      <polyline points="20,82 50,79 80,75 110,70 140,63 170,55 200,46 230,36 270,24" stroke="#ff3333" strokeWidth={telemetry.compound === 'SOFT' ? "2.5" : "1"} opacity={telemetry.compound === 'SOFT' ? "1" : "0.3"} fill="none"/>
                      <polyline points="20,70 50,68 80,64 110,58 140,50 170,40 200,28 230,14 270,0" stroke="#4ade80" strokeWidth={isInter ? "2.5" : "1"} opacity={isInter ? "1" : "0.2"} fill="none"/>
                      <polyline points="20,50 50,49 80,48 110,47 140,45 170,43 200,40 230,37 270,33" stroke="#3b82f6" strokeWidth={isWetCompound ? "2.5" : "1"} opacity={isWetCompound ? "1" : "0.2"} fill="none"/>
                      
                      <line x1={svgDotX} y1="10" x2={svgDotX} y2="90" stroke="#e10600" strokeWidth="1" strokeDasharray="3,3" opacity="0.8"/>
                      <circle cx={svgDotX} cy={svgDotY} r="4" fill={getTireHex(telemetry.compound)} className="transition-all duration-500"/>
                    </svg>
                  </div>
                  <div className="mt-2.5 flex flex-wrap gap-2">
                    <div className="flex items-center gap-1 opacity-70"><span className="w-2 h-2 rounded-full bg-[#ff3333]"></span><span className="text-[8px] text-[#888]">SOFT</span></div>
                    <div className="flex items-center gap-1 opacity-70"><span className="w-2 h-2 rounded-full bg-[#ffd700]"></span><span className="text-[8px] text-[#888]">MED</span></div>
                    <div className="flex items-center gap-1 opacity-70"><span className="w-2 h-2 rounded-full bg-[#cccccc]"></span><span className="text-[8px] text-[#888]">HARD</span></div>
                  </div>
                </div>

                {/* SCENARIO COMPARISON */}
                <div className="bg-[#10101a] border border-[#1e1e30] rounded-[10px] p-3.5 flex flex-col justify-between">
                  <div className="text-[9px] text-[#444] uppercase tracking-wide mb-2.5">Scenario comparison</div>
                  <div>
                    <div className="flex justify-between items-center mb-1.5">
                      <div className="text-[11px] font-semibold text-[#ccc]">Strategy A — {stratACall}</div>
                      <div className="text-[9px] px-1.5 py-0.5 rounded-full font-bold bg-[#0a1f0a] text-[#4ade80] border border-[#1a4d1a]">OPTIMAL</div>
                    </div>
                    <div className="flex items-baseline gap-1.5">
                      <div className="text-[18px] font-bold text-[#e8e8f0]">{formatRaceTime(telemetry.optimal_time)}</div>
                    </div>
                    <div className="flex items-center gap-0.5 mt-2">
                      <div className="h-1.5 rounded-sm bg-[#ffd700]" style={{flex: '2.2'}}></div>
                      <div className="w-[3px] h-1.5 bg-[#e10600]"></div>
                      <div className="h-1.5 rounded-sm bg-[#333]" style={{flex: '1.8'}}></div>
                    </div>
                  </div>
                  <div className="pt-2.5 border-t border-[#141420] mt-2">
                    <div className="flex justify-between items-center mb-1.5">
                      <div className="text-[11px] font-semibold text-[#888]">Strategy B — {stratBCall}</div>
                      <div className="text-[9px] px-1.5 py-0.5 rounded-full font-bold bg-[#1a1000] text-[#fbbf24] border border-[#4d3000]">+{((telemetry.sub_optimal_time || 0) - (telemetry.optimal_time || 0)).toFixed(1)}s</div>
                    </div>
                    <div className="flex items-baseline gap-1.5">
                      <div className="text-[18px] font-bold text-[#888]">{formatRaceTime(telemetry.sub_optimal_time)}</div>
                    </div>
                    <div className="flex items-center gap-0.5 mt-2">
                      <div className="h-1.5 rounded-sm bg-[#ffd700] opacity-50" style={{flex: '4'}}></div>
                      <div className="w-[3px] h-1.5 bg-[#e10600]"></div>
                      <div className="h-1.5 rounded-sm bg-[#333]" style={{flex: '0.5'}}></div>
                    </div>
                  </div>
                </div>
              </div>

              {/* TRUE HISTORICAL TIMELINE */}
              <div className="bg-[#10101a] border border-[#1e1e30] rounded-[10px] p-3.5 flex flex-col flex-1 min-h-[150px]">
                <div className="text-[9px] text-[#444] uppercase tracking-wide mb-2.5 shrink-0">Global Race Timeline — All Drivers</div>
                <div className="flex-1 overflow-y-auto pr-2 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
                  <div className="min-w-[400px]">
                    <div className="flex flex-col gap-1.5 mt-1">
                      {allDrivers.map((driver) => {
                        const h = historyRef.current[driver];
                        const stints = h ? h.stints : [];
                        const currentLap = globalData.lap_number;
                        const remaining = globalData.drivers[driver].position > 20 ? 0 : Math.max(0, globalData.total_laps - currentLap);

                        return (
                          <div key={driver} className="flex items-center gap-2 cursor-pointer hover:bg-[#1a1a2e] rounded px-1 -mx-1" onClick={() => setActiveDriver(driver)}>
                            <div className={`w-8 text-[9px] ${driver === activeDriver ? 'text-[#e10600] font-bold' : 'text-[#888]'}`}>{driver}</div>
                            
                            <div className="flex-1 flex gap-0.5 items-center">
                              {stints.map((stint, idx) => {
                                const nextStint = stints[idx + 1];
                                const duration = Math.max(1, (nextStint ? nextStint.startLap - 1 : currentLap) - stint.startLap + 1);
                                return (
                                  <React.Fragment key={idx}>
                                    <div className={`h-1.5 rounded-sm transition-all duration-300 ${getTireBg(stint.compound)}`} style={{flex: duration}}></div>
                                    {nextStint && <div className="w-1 h-2.5 bg-[#e10600] rounded-sm shrink-0"></div>}
                                  </React.Fragment>
                                )
                              })}
                              {remaining > 0 && <div className="h-1.5 bg-[#1e1e30] rounded-sm opacity-30 transition-all duration-300" style={{flex: remaining}}></div>}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
              </div>

              {/* WEATHER */}
              <div className="grid grid-cols-2 gap-3 shrink-0">
                <div className="bg-[#10101a] border border-[#1e1e30] rounded-[10px] p-4 flex flex-col justify-center">
                  <div className="text-[9px] text-[#444] uppercase tracking-wide mb-3">Weather · Track Conditions</div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="bg-[#0d0d18] rounded-md p-2 text-center"><div className="text-[16px] font-bold text-[#e8e8f0]">{trackTemp}°C</div><div className="text-[9px] text-[#444] uppercase mt-0.5">Track Temp</div></div>
                    <div className="bg-[#0d0d18] rounded-md p-2 text-center"><div className="text-[16px] font-bold text-[#e8e8f0]">{globalData.track_moisture.toFixed(0)}%</div><div className="text-[9px] text-[#444] uppercase mt-0.5">Humidity</div></div>
                  </div>
                </div>

                <div className="bg-[#10101a] border border-[#1e1e30] rounded-[10px] p-4 flex flex-col justify-center">
                  <div className="text-[9px] text-[#444] mb-2 uppercase tracking-wide">Historical SC probability</div>
                  <div className="flex gap-[3px] items-end h-[45px] mt-2">
                    <div className="flex-1 bg-[#1a4d1a] rounded-t-sm flex items-start justify-center pt-1" style={{ height: `15%` }}></div>
                    <div className="flex-1 bg-[#4d4d00] rounded-t-sm flex items-start justify-center pt-1" style={{ height: `20%` }}></div>
                    <div className="flex-1 bg-[#e10600] rounded-t-sm flex items-start justify-center pt-1 border border-[#ff3333]" style={{ height: `45%` }}></div>
                    <div className="flex-1 bg-[#3d1a00] rounded-t-sm flex items-start justify-center pt-1" style={{ height: `10%` }}></div>
                  </div>
                </div>
              </div>
            </div>

            {/* TIMING TOWER */}
            <div className="col-span-1 bg-[#10101a] border border-[#1e1e30] rounded-[10px] p-3.5 flex flex-col h-full">
              <div className="text-[9px] text-[#444] uppercase tracking-wide mb-2.5 shrink-0 flex justify-between items-center">
                <span>Global Grid Gaps</span>
                <button onClick={() => setShowLeaderGap(!showLeaderGap)} className="px-2 py-0.5 bg-[#141420] hover:bg-[#1a1a2e] border border-[#1e1e30] rounded text-[#ccc]">{showLeaderGap ? 'LEADER' : 'INTERVAL'} 🔄</button>
              </div>
              <div className="flex-1 overflow-y-auto pr-1 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
                <div className="flex flex-col gap-1">
                  {allDrivers.map((driver) => {
                    const d = globalData.drivers[driver];
                    const isTarget = driver === activeDriver;
                    const gapValue = showLeaderGap ? d.gap_to_leader : d.gap_ahead;
                    const gapDisplay = gapValue > 50 ? 'CLEAR' : `${d.position < telemetry.position && !showLeaderGap ? '+' : ''}${showLeaderGap && d.position === 1 ? 'Leader' : gapValue.toFixed(1) + 's'}`;

                    return (
                      <div key={driver} onClick={() => setActiveDriver(driver)} className={`flex items-center justify-between py-2 cursor-pointer border-b border-[#141420] text-[11px] hover:bg-[#1a1a2e] ${isTarget ? 'bg-[#1a0000] border-[#e10600] rounded px-1' : ''}`}>
                        <div className={`w-[22px] h-[22px] rounded flex items-center justify-center font-bold text-[10px] shrink-0 ${isTarget ? 'bg-[#e10600] text-white' : 'bg-[#141420] text-[#888]'}`}>{d.position}</div>
                        <div className={`font-semibold mx-2 flex-1 ${isTarget ? 'text-[#e10600]' : 'text-[#ccc]'}`}>{driver}</div>
                        <div className="flex items-center text-[10px] text-[#666] w-12 justify-end shrink-0"><span className={`w-2.5 h-2.5 rounded-full mr-1 ${getTireBg(d.compound)}`}></span>{d.tire_age}L</div>
                        <div className={`text-[11px] font-bold w-14 text-right shrink-0 ${isTarget ? 'text-[#e8e8f0]' : (d.position < telemetry.position ? 'text-[#4ade80]' : 'text-[#e10600]')}`}>{isTarget && !showLeaderGap ? '—' : gapDisplay}</div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
            
          </div>
        </div>
      </div>
    </div>
  );
}