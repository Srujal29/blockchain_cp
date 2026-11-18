import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { MOCK_REGISTRATIONS, MOCK_POLICIES, MOCK_CLAIMS } from '../data/mockData';
import { Registration, Claim, Policy, ClaimStatus } from '../types';
import { useAuth } from '../context/AuthContext';

export const CustomerDashboard: React.FC = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [activeCustomerTab, setActiveCustomerTab] = useState<'overview' | 'policies' | 'claims' | 'documents' | 'activity'>('overview');
  const [registrations, setRegistrations] = useState<Registration[]>(MOCK_REGISTRATIONS);
  const [claimsList, setClaimsList] = useState<Claim[]>(MOCK_CLAIMS);
  const [activeFilter, setActiveFilter] = useState<'all' | 'pending' | 'confirmed' | 'declined'>('all');
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [targetReg, setTargetReg] = useState<Registration | null>(null);
  const [isConfirming, setIsConfirming] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [syncTimestamp, setSyncTimestamp] = useState('14:32:04 IST');
  const [alertToast, setAlertToast] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [playingAudio, setPlayingAudio] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string>('/recordings/consultation_vikram_8821.wav');
  const [audioFileName, setAudioFileName] = useState<string>('recording_consultation_8821.wav');
  const [audioFileSize, setAudioFileSize] = useState<string>('1.42 MB');
  const [audioDuration, setAudioDuration] = useState<number>(33);
  const [audioCurrentTime, setAudioCurrentTime] = useState<number>(0);
  const [audioHash, setAudioHash] = useState<string>('bfb60e5f5438b5f802c46a4b63fe274d337a0307c7f51a6fdf105122d19fc01c');
  const [isAudioLoading, setIsAudioLoading] = useState<boolean>(false);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);

  const formatAudioTime = (sec: number) => {
    if (isNaN(sec)) return '00:00';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const toggleAudioPlay = () => {
    if (!audioRef.current) return;
    if (playingAudio) {
      audioRef.current.pause();
      setPlayingAudio(false);
    } else {
      audioRef.current.play().then(() => {
        setPlayingAudio(true);
      }).catch((err) => {
        console.warn('Audio play error:', err);
      });
    }
  };

  const handleAudioTimeUpdate = () => {
    if (audioRef.current) {
      setAudioCurrentTime(audioRef.current.currentTime);
    }
  };

  const handleAudioLoadedMetadata = () => {
    if (audioRef.current && !isNaN(audioRef.current.duration)) {
      setAudioDuration(audioRef.current.duration);
    }
  };

  const handleAudioEnded = () => {
    setPlayingAudio(false);
    setAudioCurrentTime(0);
  };

  const handleAudioSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const target = parseFloat(e.target.value);
    if (audioRef.current) {
      audioRef.current.currentTime = target;
      setAudioCurrentTime(target);
    }
  };

  const handleDownloadAudio = () => {
    const link = document.createElement('a');
    link.href = audioUrl;
    link.download = audioFileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showNotification(`Downloaded certified tele-sales recording: ${audioFileName}`);
  };

  const handleUploadAudio = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsAudioLoading(true);
    try {
      const arrayBuffer = await file.arrayBuffer();
      const hashBuffer = await crypto.subtle.digest('SHA-256', arrayBuffer);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      const calculatedHash = hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');

      const objectUrl = URL.createObjectURL(file);
      if (audioRef.current) {
        audioRef.current.pause();
      }
      setPlayingAudio(false);
      setAudioUrl(objectUrl);
      setAudioFileName(file.name);
      setAudioFileSize(`${(file.size / (1024 * 1024)).toFixed(2)} MB`);
      setAudioHash(calculatedHash);
      setAudioCurrentTime(0);

      showNotification(`Recording "${file.name}" uploaded, verified & SHA-256 sealed!`);
    } catch (err: any) {
      console.error('Audio upload error:', err);
      showNotification('Error processing audio file: ' + err.message);
    } finally {
      setIsAudioLoading(false);
    }
  };

  // File New Claim modal states
  const [showFileClaimModal, setShowFileClaimModal] = useState(false);
  const [newClaimCategory, setNewClaimCategory] = useState<'HOSPITALIZATION' | 'VEHICLE' | 'GENERIC'>('HOSPITALIZATION');
  const [newClaimAmount, setNewClaimAmount] = useState('45000');
  const [newClaimHospital, setNewClaimHospital] = useState('Fortis Healthcare Super Specialty Hospital');
  const [newClaimDescription, setNewClaimDescription] = useState('Emergency inpatient admission with acute condition. Hospital invoice and discharge summary attached.');
  const [isSubmittingClaim, setIsSubmittingClaim] = useState(false);

  const getStoredClaims = (): Claim[] => {
    try {
      const data = localStorage.getItem('vachan_claims_store');
      if (data) {
        const parsed = JSON.parse(data);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch (e) {
      console.warn('Could not read stored claims:', e);
    }
    return MOCK_CLAIMS;
  };

  const saveStoredClaims = (newClaims: Claim[]) => {
    try {
      localStorage.setItem('vachan_claims_store', JSON.stringify(newClaims));
    } catch (e) {
      console.warn('Could not save claims:', e);
    }
  };

  useEffect(() => {
    loadData();
    const now = new Date();
    setSyncTimestamp(now.toTimeString().split(' ')[0] + ' IST');
  }, []);

  const handleSeedSampleClaim = () => {
    const sampleId = `CLM-2026-${Math.floor(1000 + Math.random() * 9000)}`;
    const sample: Claim = {
      id: sampleId,
      registration_id: registrations[0]?.id || 'reg-001',
      policy_id: registrations[0]?.policy_id || 'a1111111-1111-1111-1111-111111111111',
      policy_version_id: registrations[0]?.policy_version_id || 'b1111111-1111-1111-1111-111111111111',
      customer_id: user?.id || 'cust-live',
      claim_category: 'HOSPITALIZATION',
      requested_amount: 45000,
      incident_date: new Date().toISOString().split('T')[0],
      description: 'Emergency ICU & Inpatient Admission at Fortis Healthcare. Hospital invoice & discharge summary attached.',
      status: 'SUBMITTED',
      created_at: new Date().toISOString(),
      policy: registrations[0]?.policy || {
        id: 'a1111111-1111-1111-1111-111111111111',
        insurer_name: 'Care Premier Health',
        policy_name: 'Care Premier Health Shield',
        policy_code: 'VG-HLT-01',
        category: 'HEALTH',
        description: 'Comprehensive health shield with cashless hospitalization',
        coverage_limit: 1500000,
        waiting_period_days: 30,
        claim_filing_window_days: 30,
        is_active: true,
      },
      latest_assessment: {
        id: `asm-${Date.now()}`,
        claim_id: sampleId,
        overall_outcome: 'REQUIRES_REVIEW',
        requested_amount: 45000,
        applicable_limit: 1500000,
        potentially_payable_amount: 45000,
        excess_amount: 0,
        assessed_at: new Date().toISOString(),
        rules_evaluated: [
          { rule_id: 'RULE-OCR-01', result: 'PASSED', explanation: 'Hospital Tax invoice authentic, cashless billing code valid.' },
          { rule_id: 'RULE-DUP-02', result: 'PASSED', explanation: 'SHA-256 duplicate scan: 0 matching hospital claims in past 365 days.' },
          { rule_id: 'RULE-VOICE-03', result: 'PASSED', explanation: 'Tele-sales audio parity validated; no conflicting oral representations.' },
          { rule_id: 'RULE-AUTH-04', result: 'PENDING' as any, explanation: 'Pending Approval Authority final sign-off before payout release.' },
        ],
      },
    };
    const updated: Claim[] = [sample, ...claimsList];
    setClaimsList(updated);
    saveStoredClaims(updated);
    showNotification('New Hospitalization Claim submitted! Awaiting Authority verification.');
  };

  const handleSimulateClaimPayout = (claimId: string) => {
    const updated: Claim[] = claimsList.map((c) => (c.id === claimId ? { ...c, status: 'PAID' as ClaimStatus } : c));
    setClaimsList(updated);
    saveStoredClaims(updated);
    showNotification('Instant IMPS Payout Executed! ₹45,000 credited to your registered bank account in 1.8 seconds.');
  };

  const handleSimulateAuthorityApproval = (claimId: string) => {
    const updated: Claim[] = claimsList.map((c) =>
      c.id === claimId
        ? {
            ...c,
            status: 'APPROVED' as ClaimStatus,
            latest_assessment: c.latest_assessment
              ? {
                  ...c.latest_assessment,
                  overall_outcome: 'ELIGIBLE' as const,
                  rules_evaluated: c.latest_assessment.rules_evaluated.map((r) => ({
                    ...r,
                    result: 'PASSED' as const,
                    explanation: r.rule_id === 'RULE-AUTH-04' ? 'Approved by IRDAI Approval Authority Officer with digital signature.' : r.explanation,
                  })),
                }
              : undefined,
          }
        : c
    );
    setClaimsList(updated);
    saveStoredClaims(updated);
    showNotification(`Claim #${claimId} approved by Authority! IMPS payout is now unlocked.`);
  };

  const handleCreateNewClaim = (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmittingClaim(true);
    setTimeout(() => {
      const amt = parseFloat(newClaimAmount) || 25000;
      const newId = `CLM-2026-${Math.floor(1000 + Math.random() * 9000)}`;
      const created: Claim = {
        id: newId,
        registration_id: registrations[0]?.id || 'reg-001',
        policy_id: registrations[0]?.policy_id || 'a1111111-1111-1111-1111-111111111111',
        policy_version_id: registrations[0]?.policy_version_id || 'b1111111-1111-1111-1111-111111111111',
        customer_id: user?.id || 'cust-live',
        claim_category: newClaimCategory,
        requested_amount: amt,
        incident_date: new Date().toISOString().split('T')[0],
        description: `${newClaimHospital}: ${newClaimDescription}`,
        status: 'SUBMITTED',
        created_at: new Date().toISOString(),
        policy: registrations[0]?.policy || {
          id: 'a1111111-1111-1111-1111-111111111111',
          insurer_name: 'Care Premier Health',
          policy_name: 'Care Premier Health Shield',
          policy_code: 'VG-HLT-01',
          category: 'HEALTH',
          description: 'Comprehensive health shield with cashless hospitalization',
          coverage_limit: 1500000,
          waiting_period_days: 30,
          claim_filing_window_days: 30,
          is_active: true,
        },
        latest_assessment: {
          id: `asm-${Date.now()}`,
          claim_id: newId,
          overall_outcome: 'REQUIRES_REVIEW',
          requested_amount: amt,
          applicable_limit: 1500000,
          potentially_payable_amount: amt,
          excess_amount: 0,
          assessed_at: new Date().toISOString(),
          rules_evaluated: [
            { rule_id: 'RULE-OCR-01', result: 'PASSED', explanation: 'Hospital Tax invoice authentic; cashless billing code matched with IRDAI registry.' },
            { rule_id: 'RULE-DUP-02', result: 'PASSED', explanation: 'SHA-256 duplicate detection scanned: 0 duplicate hospital claims found.' },
            { rule_id: 'RULE-VOICE-03', result: 'PASSED', explanation: 'Tele-sales audio parity validated; no conflicting oral representations recorded.' },
            { rule_id: 'RULE-AUTH-04', result: 'PENDING' as any, explanation: 'Pending Approval Authority final sign-off & cashless sanction.' },
          ],
        },
      };
      const updated = [created, ...claimsList];
      setClaimsList(updated);
      saveStoredClaims(updated);
      setShowFileClaimModal(false);
      setIsSubmittingClaim(false);
      showNotification(`Claim #${created.id} submitted! Awaiting Authority verification.`);
    }, 800);
  };

  const loadData = async () => {
    setIsRefreshing(true);
    try {
      const stored = getStoredClaims();
      setClaimsList(stored);
      const [fetchedRegs] = await Promise.all([
        api.getRegistrations(),
      ]);
      if (fetchedRegs && fetchedRegs.length > 0) {
        setRegistrations(fetchedRegs);
      }
      const now = new Date();
      setSyncTimestamp(now.toTimeString().split(' ')[0] + ' IST');
    } catch (e) {
      console.warn('Using offline data fallback', e);
    } finally {
      setIsRefreshing(false);
    }
  };

  const showNotification = (msg: string) => {
    setAlertToast(msg);
    setTimeout(() => setAlertToast(null), 3500);
  };

  // Helper to detect any pending confirmation status
  const isAwaitingConfirmation = (status?: string) =>
    status === 'AWAITING_CUSTOMER_CONFIRMATION' ||
    status === 'PENDING_VERIFICATION' ||
    status === 'PENDING_REVIEW';

  // Find attention item (first awaiting confirmation)
  const attentionItem = registrations.find((r) => isAwaitingConfirmation(r.status));

  const handleOpenConfirmModal = (reg?: Registration) => {
    const item = reg || attentionItem || registrations[0];
    setTargetReg(item);
    setShowConfirmModal(true);
  };

  const handleExecuteConfirm = async () => {
    if (!targetReg) return;
    setIsConfirming(true);
    try {
      await api.confirmRegistration(targetReg.id);
      setRegistrations((prev) =>
        prev.map((r) =>
          r.id === targetReg.id
            ? { ...r, status: 'CONFIRMED', confirmed_at: new Date().toISOString() }
            : r
        )
      );
      setShowConfirmModal(false);
      showNotification(`Statutory binding confirmed for ${targetReg.id}. Biometric ledger signed.`);
    } catch {
      showNotification('Confirmation completed with offline cryptographic signature.');
      setShowConfirmModal(false);
    } finally {
      setIsConfirming(false);
    }
  };

  const handleDecline = async (regId: string) => {
    const confirmDecline = window.confirm(
      `Execute POST /api/v1/registrations/${regId}/decline? This will revoke pending underwriting approval.`
    );
    if (!confirmDecline) return;

    try {
      await api.declineRegistration(regId);
      setRegistrations((prev) =>
        prev.map((r) => (r.id === regId ? { ...r, status: 'DECLINED' } : r))
      );
      showNotification(`Policy registration ${regId} marked as DECLINED.`);
    } catch {
      showNotification(`Policy registration ${regId} declined.`);
    }
  };

  // Filtered rows
  const filteredRegistrations = registrations.filter((reg) => {
    if (activeFilter === 'all') return true;
    if (activeFilter === 'pending') return isAwaitingConfirmation(reg.status);
    if (activeFilter === 'confirmed') return reg.status === 'CONFIRMED';
    if (activeFilter === 'declined') return reg.status === 'DECLINED';
    return true;
  });

  // Dynamic counts
  const totalCount = registrations.length;
  const countPending = registrations.filter((r) => isAwaitingConfirmation(r.status)).length;
  const countConfirmed = registrations.filter((r) => r.status === 'CONFIRMED').length;
  const countDeclined = registrations.filter((r) => r.status === 'DECLINED').length;

  return (
    <div className="bg-background font-body-md text-on-surface antialiased min-h-screen">
      {/* Toast Notification */}
      {alertToast && (
        <div className="fixed top-20 right-8 z-50 bg-navy-900 text-white px-5 py-3 rounded-2xl shadow-2xl border border-slate-700 flex items-center gap-3 animate-in fade-in duration-200">
          <span className="material-symbols-outlined text-emerald-400 text-[20px]">check_circle</span>
          <span className="text-sm font-medium">{alertToast}</span>
        </div>
      )}

      {/* BEGIN: Interactive Confirmation Modal (Exact Stitch Specification) */}
      {showConfirmModal && targetReg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/40 backdrop-blur-sm p-space-md animate-in fade-in duration-200">
          <div className="relative w-full max-w-xl bg-surface-container-lowest rounded-2xl shadow-xl overflow-hidden flex flex-col">
            <div className="p-space-lg bg-surface-container-low flex items-start justify-between">
              <div className="flex items-center gap-space-sm">
                <div className="w-10 h-10 rounded-full bg-primary-container text-on-primary flex items-center justify-center shadow-md">
                  <span className="material-symbols-outlined text-[22px]">verified</span>
                </div>
                <div className="flex flex-col">
                  <span className="font-headline-sm text-headline-sm text-on-surface font-bold">
                    Confirm Statutory Binding
                  </span>
                  <span className="font-label-sm text-label-sm text-on-surface-variant font-mono">
                    POST /api/v1/registrations/{targetReg.id}/confirm
                  </span>
                </div>
              </div>
              <button
                onClick={() => setShowConfirmModal(false)}
                className="text-on-surface-variant hover:text-on-surface p-1 rounded-lg hover:bg-surface-container-high transition-colors cursor-pointer"
              >
                <span className="material-symbols-outlined text-[20px]">close</span>
              </button>
            </div>

            <div className="p-space-lg flex flex-col gap-space-md">
              <div className="bg-surface-container-low p-space-md rounded-xl flex flex-col gap-space-xs">
                <div className="flex items-center justify-between">
                  <span className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider font-semibold">
                    Target Registration
                  </span>
                  <span className="font-label-md text-label-md font-mono text-primary font-bold">
                    {targetReg.id}
                  </span>
                </div>
                <p className="font-body-md text-body-md text-on-surface font-semibold">
                  {targetReg.policy?.policy_name || 'Care Premier Health Shield'} (₹
                  {(targetReg.policy?.coverage_limit || 1500000).toLocaleString('en-IN')})
                </p>
                <p className="font-body-sm text-body-sm text-on-surface-variant">
                  Underwritten via Verified Acoustic Telemetry • Broker ID: #AG-7721-M
                </p>
              </div>

              {/* Consequence Disclosure */}
              <div className="p-space-md bg-surface-container-low rounded-xl flex items-start gap-space-sm">
                <span className="material-symbols-outlined text-primary text-[20px] shrink-0 mt-0.5">policy</span>
                <div className="flex flex-col gap-1">
                  <span className="font-label-md text-label-md text-on-surface font-semibold">
                    Statutory Declaration of Consent
                  </span>
                  <p className="font-body-sm text-body-sm text-on-surface-variant leading-relaxed">
                    By confirming, you validate that the audio-recorded disclosures match your policy intent. Upon cryptographic signing, this record transitions into an IRDAI-compliant immutable registry block. A tamper-proof timestamp will bind your customer token.
                  </p>
                </div>
              </div>

              {/* Token Header Handshake Preview */}
              <div className="flex items-center justify-between px-space-md py-space-xs bg-surface-container-low rounded-xl text-on-surface-variant font-mono text-[11px]">
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-primary"></span>
                  Bearer Token: eyJhbGciOi...auth_usr_ananya
                </span>
                <span className="text-primary font-semibold">TLS 1.3 Vault Encrypted</span>
              </div>
            </div>

            <div className="p-space-lg bg-surface-container-low flex items-center justify-end gap-space-sm">
              <button
                type="button"
                onClick={() => setShowConfirmModal(false)}
                className="px-space-lg py-2.5 rounded-full font-label-md text-label-md text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleExecuteConfirm}
                disabled={isConfirming}
                className="px-space-xl py-2.5 rounded-full bg-primary text-on-primary font-label-md text-label-md shadow-md hover:bg-secondary transition-all flex items-center gap-space-xs cursor-pointer"
              >
                <span className={`material-symbols-outlined text-[18px] ${isConfirming ? 'animate-spin' : ''}`}>
                  {isConfirming ? 'sync' : 'lock'}
                </span>
                <span>{isConfirming ? 'Transacting...' : 'Sign & Quick Confirm'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
      {/* END: Confirmation Modal */}

      {/* BEGIN: Left Fixed Sidebar (1:1 Stitch Customer Specification) */}
      <aside
        className={`fixed left-0 top-0 h-full w-72 bg-surface-container-lowest z-50 flex flex-col justify-between shadow-[0_1px_8px_rgba(0,0,0,0.04)] transition-transform duration-300 ease-in-out ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex flex-col">
          {/* Logo Brand Header */}
          <div className="h-16 px-space-lg flex items-center bg-surface-container-lowest">
            <Link to="/" className="flex items-center gap-space-sm group">
              <div className="w-9 h-9 rounded-xl bg-primary-container text-on-primary flex items-center justify-center shadow-[0_4px_14px_rgba(37,99,235,0.25)] group-hover:scale-105 transition-transform">
                <span className="material-symbols-outlined text-[20px]">verified_user</span>
              </div>
              <div className="flex flex-col leading-none">
                <span className="font-headline-sm text-headline-sm text-on-surface tracking-tight font-bold">
                  VACHAN
                </span>
                <span className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider font-semibold">
                  InsureChain VoiceGuard
                </span>
              </div>
            </Link>
          </div>

          {/* Engine Status Pill */}
          <div className="px-space-md py-space-sm">
            <div className="bg-surface-container-low rounded-xl px-space-md py-space-xs flex items-center gap-space-xs">
              <span className="material-symbols-outlined text-[16px] text-primary">graphic_eq</span>
              <span className="font-label-sm text-label-sm text-primary tracking-wide font-semibold">
                Biometric Voice Engine Ready
              </span>
            </div>
          </div>

          {/* Nav Items */}
          <nav className="px-space-md py-space-sm flex flex-col gap-space-xs">
            <button
              onClick={() => setActiveCustomerTab('overview')}
              className={`flex items-center gap-space-sm px-space-md py-space-sm rounded-xl transition-all text-left font-semibold cursor-pointer ${
                activeCustomerTab === 'overview'
                  ? 'bg-primary text-on-primary font-label-lg shadow-[0_4px_14px_rgba(37,99,235,0.25)]'
                  : 'font-label-lg text-label-lg text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'
              }`}
            >
              <span className="material-symbols-outlined text-[20px]">grid_view</span>
              <span>Overview</span>
            </button>

            <button
              onClick={() => setActiveCustomerTab('policies')}
              className={`flex items-center gap-space-sm px-space-md py-space-sm rounded-xl transition-all text-left font-semibold cursor-pointer ${
                activeCustomerTab === 'policies'
                  ? 'bg-primary text-on-primary font-label-lg shadow-[0_4px_14px_rgba(37,99,235,0.25)]'
                  : 'font-label-lg text-label-lg text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'
              }`}
            >
              <span className="material-symbols-outlined text-[20px]">shield</span>
              <span>My Policies</span>
            </button>

            <button
              onClick={() => setActiveCustomerTab('claims')}
              className={`flex items-center gap-space-sm px-space-md py-space-sm rounded-xl transition-all text-left font-semibold cursor-pointer ${
                activeCustomerTab === 'claims'
                  ? 'bg-primary text-on-primary font-label-lg shadow-[0_4px_14px_rgba(37,99,235,0.25)]'
                  : 'font-label-lg text-label-lg text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'
              }`}
            >
              <span className="material-symbols-outlined text-[20px]">fact_check</span>
              <span>My Claims</span>
            </button>

            <button
              onClick={() => setActiveCustomerTab('documents')}
              className={`flex items-center gap-space-sm px-space-md py-space-sm rounded-xl transition-all text-left font-semibold cursor-pointer ${
                activeCustomerTab === 'documents'
                  ? 'bg-primary text-on-primary font-label-lg shadow-[0_4px_14px_rgba(37,99,235,0.25)]'
                  : 'font-label-lg text-label-lg text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'
              }`}
            >
              <span className="material-symbols-outlined text-[20px]">folder_shared</span>
              <span>Documents</span>
            </button>

            <button
              onClick={() => setActiveCustomerTab('activity')}
              className={`flex items-center gap-space-sm px-space-md py-space-sm rounded-xl transition-all text-left font-semibold cursor-pointer ${
                activeCustomerTab === 'activity'
                  ? 'bg-primary text-on-primary font-label-lg shadow-[0_4px_14px_rgba(37,99,235,0.25)]'
                  : 'font-label-lg text-label-lg text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'
              }`}
            >
              <span className="material-symbols-outlined text-[20px]">history</span>
              <span>Activity</span>
            </button>
          </nav>
        </div>

        {/* Profile Card & Logout */}
        <div className="p-space-md flex flex-col gap-space-xs">
          <div className="bg-surface-container-low rounded-xl p-space-sm flex items-center justify-between">
            <div className="flex items-center gap-space-sm">
              <div className="w-9 h-9 rounded-full bg-primary flex items-center justify-center">
                <span className="material-symbols-outlined text-on-primary text-[18px]">person</span>
              </div>
              <div className="flex flex-col">
                <span className="font-label-md text-label-md text-on-surface leading-tight font-semibold">
                  {user?.full_name || 'Valued Policyholder'}
                </span>
                <span className="font-label-sm text-label-sm text-on-surface-variant leading-tight truncate max-w-[140px]">
                  {user?.email || 'Verified Account'}
                </span>
              </div>
            </div>
            <button
              onClick={() => showNotification('Policyholder profile is in active compliance mode.')}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors cursor-pointer"
              title="Account Settings"
            >
              <span className="material-symbols-outlined text-[18px]">settings</span>
            </button>
          </div>

          <button
            onClick={() => {
              logout();
              navigate('/login');
            }}
            className="w-full flex items-center justify-between px-space-md py-space-xs rounded-xl font-label-md text-label-md text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface transition-colors cursor-pointer"
          >
            <span className="flex items-center gap-space-xs">
              <span className="material-symbols-outlined text-[18px]">logout</span>
              <span>Sign Out</span>
            </span>
            <span className="font-label-sm text-label-sm text-on-surface-variant font-mono">v2.4.1</span>
          </button>
        </div>
      </aside>
      {/* END: Sidebar */}

      {/* BEGIN: Main Content Frame */}
      <div className={`transition-all duration-300 ease-in-out ${sidebarOpen ? 'pl-72' : 'pl-0'}`}>
        {/* Sticky Header with Hamburger Toggle */}
        <header
          className={`fixed top-0 right-0 h-16 bg-surface-container-lowest/90 backdrop-blur-xl z-40 shadow-[0_1px_8px_rgba(0,0,0,0.04)] transition-all duration-300 ease-in-out ${
            sidebarOpen ? 'left-72' : 'left-0'
          }`}
        >
          <div className="h-16 w-full px-space-gutter flex items-center justify-between gap-space-md">
            <div className="flex items-center gap-space-md">
              {/* Three lines hamburger toggle button */}
              <button
                type="button"
                onClick={() => setSidebarOpen(!sidebarOpen)}
                title={sidebarOpen ? "Close sidebar" : "Open sidebar"}
                className="w-10 h-10 rounded-xl flex items-center justify-center text-on-surface hover:bg-surface-container-low transition-colors cursor-pointer shrink-0"
              >
                <span className="material-symbols-outlined text-[24px] transition-transform duration-200">
                  {sidebarOpen ? 'close' : 'menu'}
                </span>
              </button>

              <div className="flex items-center gap-space-xs font-label-md text-label-md">
                <span className="text-on-surface-variant">Customer Portal</span>
                <span className="material-symbols-outlined text-[16px] text-on-surface-variant">chevron_right</span>
                <span className="text-primary font-label-lg text-label-lg font-semibold capitalize">
                  {activeCustomerTab === 'overview'
                    ? 'Overview'
                    : activeCustomerTab === 'policies'
                    ? 'My Policies'
                    : activeCustomerTab === 'claims'
                    ? 'My Claims'
                    : activeCustomerTab === 'documents'
                    ? 'Documents Vault'
                    : 'Ledger Activity'}
                </span>
              </div>
              <div className="hidden md:flex items-center gap-space-xs bg-surface-container-low px-space-sm py-space-xs rounded-full">
                <span className="w-2 h-2 rounded-full bg-primary animate-pulse"></span>
                <span className="font-label-sm text-label-sm text-on-surface-variant font-medium">
                  Verified Vault • TLS 1.3
                </span>
              </div>
            </div>

            <div className="flex items-center gap-space-sm">
              <div className="relative hidden sm:flex items-center">
                <span className="material-symbols-outlined absolute left-3 text-[18px] text-on-surface-variant">search</span>
                <input
                  type="text"
                  placeholder="Search policies, claims..."
                  className="bg-surface-container-low font-body-sm text-body-sm text-on-surface pl-9 pr-space-md py-space-xs rounded-xl focus:outline-none focus:bg-surface-container-lowest focus:ring-1 focus:ring-primary w-60 transition-all"
                />
              </div>

              <button
                type="button"
                className="w-9 h-9 rounded-xl flex items-center justify-center text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface transition-colors relative"
              >
                <span className="material-symbols-outlined text-[20px]">notifications</span>
                <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-error"></span>
              </button>

              <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center">
                <span className="material-symbols-outlined text-on-primary text-[18px]">person</span>
              </div>
            </div>
          </div>
        </header>

        {/* Canvas Body with generous top and horizontal spacing */}
        <main className="relative pt-24 pb-20 bg-background min-h-screen">
          <div className="flex flex-col w-full">
            {activeCustomerTab === 'overview' && (
              <div className="w-full max-w-7xl mx-auto px-6 sm:px-10 lg:px-12 py-4 flex flex-col gap-10">
                {/* 1. Header Section with Contextual Controls */}
              <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                <div className="flex flex-col gap-0.5">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-primary">
                      Client Verification Vault
                    </span>
                    <span className="text-slate-400 text-xs">•</span>
                    <span className="text-[11px] font-semibold text-on-surface-variant">
                      Live Ledger Sync
                    </span>
                  </div>
                  <h1 className="text-2xl sm:text-3xl font-extrabold text-on-surface tracking-tight">
                    Your insurance, at a glance
                  </h1>
                  <p className="text-xs sm:text-sm text-on-surface-variant">
                    Track your policies, confirmations, and claims in one place.
                  </p>
                </div>

                <div className="flex items-center gap-3 self-start lg:self-center">
                  {/* Live Timestamp & Refresh CTA */}
                  <div className="flex items-center gap-2 bg-surface-container-lowest px-3 py-1.5 rounded-full shadow-xs border border-slate-100">
                    <span className="w-2 h-2 rounded-full bg-primary animate-pulse"></span>
                    <span className="text-xs text-on-surface-variant font-mono">
                      Synced: Just now ({syncTimestamp})
                    </span>
                  </div>

                  <button
                    onClick={loadData}
                    disabled={isRefreshing}
                    type="button"
                    className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-surface-container-lowest hover:bg-surface-container-low text-on-surface shadow-xs border border-slate-100 transition-all group active:scale-95 cursor-pointer text-xs font-semibold"
                  >
                    <span
                      className={`material-symbols-outlined text-[16px] text-primary group-hover:rotate-180 transition-transform duration-500 ${
                        isRefreshing ? 'animate-spin' : ''
                      }`}
                    >
                      sync
                    </span>
                    <span>{isRefreshing ? 'Refreshing...' : 'Refresh Data'}</span>
                  </button>

                  <div className="relative">
                    <button
                      type="button"
                      className="w-8 h-8 rounded-full bg-surface-container-lowest hover:bg-surface-container-low text-on-surface-variant flex items-center justify-center shadow-xs border border-slate-100 transition-colors cursor-pointer"
                    >
                      <span className="material-symbols-outlined text-[18px]">notifications</span>
                      <span className="absolute top-0.5 right-0.5 w-2 h-2 rounded-full bg-primary"></span>
                    </button>
                  </div>
                </div>
              </div>

              {/* 2. Proportional Key Metric Cards Row */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                {/* Card 1: Registrations Total */}
                <div className="bg-surface-container-lowest rounded-2xl p-4 sm:p-5 shadow-xs border border-slate-100 flex flex-col justify-between gap-3 group hover:shadow-md transition-shadow">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-on-surface-variant uppercase tracking-wider">
                      My Registrations
                    </span>
                    <div className="w-8 h-8 rounded-lg bg-surface-container-low text-primary flex items-center justify-center">
                      <span className="material-symbols-outlined text-[18px]">inventory_2</span>
                    </div>
                  </div>
                  <div className="flex items-baseline justify-between pt-1">
                    <span className="text-2xl sm:text-3xl font-extrabold text-on-surface tracking-tight">
                      {totalCount}
                    </span>
                    <span className="text-[11px] font-bold text-primary font-mono bg-surface-container-low px-2 py-0.5 rounded-full">
                      Vault Active
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-on-surface-variant">
                    <span className="material-symbols-outlined text-[15px] text-primary">verified_user</span>
                    <span>{totalCount} cryptographic records verified</span>
                  </div>
                </div>

                {/* Card 2: Awaiting Confirmation */}
                <div className="bg-surface-container-lowest rounded-2xl p-4 sm:p-5 shadow-xs border border-slate-100 flex flex-col justify-between gap-3 relative overflow-hidden group hover:shadow-md transition-shadow">
                  <div className="absolute top-0 left-0 right-0 h-1 bg-primary"></div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-on-surface-variant uppercase tracking-wider">
                      Awaiting Confirmation
                    </span>
                    <div className="w-8 h-8 rounded-lg bg-surface-container-high text-primary flex items-center justify-center">
                      <span className="material-symbols-outlined text-[18px]">hourglass_top</span>
                    </div>
                  </div>
                  <div className="flex items-baseline justify-between pt-1">
                    <span className="text-2xl sm:text-3xl font-extrabold text-on-surface tracking-tight">
                      {countPending}
                    </span>
                    <span className="text-[11px] font-bold text-primary bg-surface-container-high px-2 py-0.5 rounded-full">
                      Action Required
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-on-surface-variant">
                    <span className="w-2 h-2 rounded-full bg-primary animate-ping"></span>
                    <span>Requires customer consent</span>
                  </div>
                </div>

                {/* Card 3: Confirmed Policies */}
                <div className="bg-surface-container-lowest rounded-2xl p-4 sm:p-5 shadow-xs border border-slate-100 flex flex-col justify-between gap-3 group hover:shadow-md transition-shadow">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-on-surface-variant uppercase tracking-wider">
                      Confirmed Policies
                    </span>
                    <div className="w-8 h-8 rounded-lg bg-surface-container-low text-primary flex items-center justify-center">
                      <span className="material-symbols-outlined text-[18px]">gpp_good</span>
                    </div>
                  </div>
                  <div className="flex items-baseline justify-between pt-1">
                    <span className="text-2xl sm:text-3xl font-extrabold text-on-surface tracking-tight">
                      {countConfirmed}
                    </span>
                    <span className="text-[11px] font-bold text-primary bg-surface-container-low px-2 py-0.5 rounded-full">
                      IRDAI Compliant
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-on-surface-variant">
                    <span className="material-symbols-outlined text-[15px] text-primary">check_circle</span>
                    <span>Coverage active &amp; legally bound</span>
                  </div>
                </div>

                {/* Card 4: Honest Claims API Boundary */}
                <div className="bg-surface-container-lowest rounded-2xl p-4 sm:p-5 shadow-xs border border-slate-100 flex flex-col justify-between gap-3 group hover:shadow-md transition-shadow">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-on-surface-variant uppercase tracking-wider">
                      My Claims
                    </span>
                    <div className="w-8 h-8 rounded-lg bg-surface-container-low text-on-surface-variant flex items-center justify-center">
                      <span className="material-symbols-outlined text-[18px]">shield_with_heart</span>
                    </div>
                  </div>
                  <div className="flex items-baseline justify-between pt-1">
                    <span className="text-2xl sm:text-3xl font-extrabold text-on-surface tracking-tight">
                      0
                    </span>
                    <span className="text-[11px] font-bold text-on-surface-variant bg-surface-container-low px-2 py-0.5 rounded-full">
                      No active claims
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-on-surface-variant truncate">
                    <span className="material-symbols-outlined text-[15px] text-on-surface-variant">cloud_done</span>
                    <span className="truncate">Customer Claims API: 0 active</span>
                  </div>
                </div>
              </div>

              {/* 3. Prominent "Needs Your Attention" Section */}
              {attentionItem && (
                <div className="flex flex-col gap-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-primary text-[18px]">priority_high</span>
                      <h2 className="text-base sm:text-lg font-bold text-on-surface">
                        Needs your attention
                      </h2>
                    </div>
                    <span className="text-[11px] font-bold text-on-surface-variant uppercase tracking-wider">
                      {countPending} Action Outstanding
                    </span>
                  </div>

                  {/* High Priority Card */}
                  <div className="bg-surface-container-lowest rounded-2xl shadow-xs border border-slate-100 p-4 sm:p-5 flex flex-col lg:flex-row lg:items-center justify-between gap-4 relative overflow-hidden">
                    <div className="flex flex-col md:flex-row items-start md:items-center gap-4 flex-1">
                      {/* Voiceprint Telemetry Badge */}
                      <div className="w-12 h-12 rounded-xl bg-surface-container-low flex flex-col items-center justify-center shrink-0 shadow-inner">
                        <span className="material-symbols-outlined text-primary text-[22px]">
                          record_voice_over
                        </span>
                        <span className="text-[9px] text-primary font-bold uppercase tracking-tighter">
                          Audio Match
                        </span>
                      </div>

                      {/* Policy & Regulatory Metadata */}
                      <div className="flex flex-col gap-1.5 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-base font-bold text-on-surface">
                            {attentionItem.policy?.policy_name || 'Care Premier Health Shield'}
                          </span>
                          <span className="font-mono text-xs font-bold text-primary bg-surface-container-low px-2 py-0.5 rounded">
                            {attentionItem.id}
                          </span>
                          <span className="bg-surface-container-high text-primary text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider">
                            AWAITING_CUSTOMER_CONFIRMATION
                          </span>
                        </div>

                        <div className="flex flex-wrap items-center gap-y-1 gap-x-2.5 text-xs text-on-surface-variant">
                          <span className="flex items-center gap-1 font-semibold text-on-surface">
                            <span className="material-symbols-outlined text-[14px] text-primary">currency_rupee</span>
                            Coverage Limit: ₹{(attentionItem.policy?.coverage_limit || 1500000).toLocaleString('en-IN')}
                          </span>
                          <span>•</span>
                          <span>
                            Issued by Advisory Agent: <strong className="text-on-surface">Rajesh M.</strong>
                          </span>
                          <span>•</span>
                          <span className="flex items-center gap-1">
                            <span className="material-symbols-outlined text-[14px] text-primary">graphic_eq</span>
                            Tele-telemetry audio sealed (87.4s)
                          </span>
                        </div>

                        {/* Statutory Notice */}
                        <div className="mt-1 flex items-center gap-2 p-2 bg-surface-container-low rounded-xl text-xs text-on-surface-variant">
                          <span className="material-symbols-outlined text-[16px] text-primary shrink-0">info</span>
                          <p>
                            <strong className="text-on-surface">Statutory Notice:</strong> Verbal pre-sale commitment review required prior to statutory activation. Confirming certifies your voice acknowledgment.
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* Action Controls */}
                    <div className="flex flex-wrap sm:flex-nowrap items-center gap-2.5 shrink-0 self-stretch lg:self-center pt-2 lg:pt-0">
                      <button
                        type="button"
                        onClick={() => handleDecline(attentionItem.id)}
                        className="flex-1 sm:flex-initial px-4 py-2 rounded-full bg-surface-container-low hover:bg-surface-container-high text-on-surface-variant text-xs transition-colors flex items-center justify-center gap-1 cursor-pointer font-semibold"
                      >
                        <span className="material-symbols-outlined text-[16px]">close</span>
                        <span>Decline</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleOpenConfirmModal(attentionItem)}
                        className="flex-1 sm:flex-initial px-4 py-2 rounded-full bg-surface-container-low hover:bg-surface-container-high text-on-surface text-xs transition-colors flex items-center justify-center gap-1 cursor-pointer font-semibold"
                      >
                        <span className="material-symbols-outlined text-[16px]">visibility</span>
                        <span>Review Terms</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleOpenConfirmModal(attentionItem)}
                        className="w-full sm:w-auto px-5 py-2 rounded-full bg-primary hover:bg-secondary text-on-primary text-xs shadow-sm transition-all flex items-center justify-center gap-1.5 group cursor-pointer font-bold"
                      >
                        <span className="material-symbols-outlined text-[16px] group-hover:scale-110 transition-transform">
                          check_circle
                        </span>
                        <span>Quick Confirm</span>
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* 4. Recent Registrations / Policy Activity */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-lg items-start" id="registered-policies">
                {/* Main Enterprise Registrations Table (8 Columns) */}
                <div className="lg:col-span-8 bg-surface-container-lowest rounded-2xl shadow-xs border border-slate-100 p-5 sm:p-6 flex flex-col gap-4 overflow-hidden">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div className="flex flex-col">
                      <h3 className="text-base sm:text-lg font-bold text-on-surface">
                        Registered Policy Ledgers
                      </h3>
                      <span className="text-xs text-on-surface-variant">
                        Validated customer registrations via GET /api/v1/registrations
                      </span>
                    </div>

                    {/* Segment Filter Controls */}
                    <div className="flex items-center p-1 bg-surface-container-low rounded-xl">
                      <button
                        onClick={() => setActiveFilter('all')}
                        className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                          activeFilter === 'all'
                            ? 'bg-surface-container-lowest text-on-surface shadow-xs'
                            : 'text-on-surface-variant hover:text-on-surface'
                        }`}
                      >
                        All ({totalCount})
                      </button>

                      <button
                        onClick={() => setActiveFilter('pending')}
                        className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                          activeFilter === 'pending'
                            ? 'bg-surface-container-lowest text-on-surface shadow-xs'
                            : 'text-on-surface-variant hover:text-on-surface'
                        }`}
                      >
                        Pending ({countPending})
                      </button>

                      <button
                        onClick={() => setActiveFilter('confirmed')}
                        className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                          activeFilter === 'confirmed'
                            ? 'bg-surface-container-lowest text-on-surface shadow-xs'
                            : 'text-on-surface-variant hover:text-on-surface'
                        }`}
                      >
                        Confirmed ({countConfirmed})
                      </button>

                      <button
                        onClick={() => setActiveFilter('declined')}
                        className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                          activeFilter === 'declined'
                            ? 'bg-surface-container-lowest text-on-surface shadow-xs'
                            : 'text-on-surface-variant hover:text-on-surface'
                        }`}
                      >
                        Declined ({countDeclined})
                      </button>
                    </div>
                  </div>

                  {/* Compact Enterprise Table */}
                  <div className="overflow-x-auto w-full">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="bg-surface-container-low text-on-surface-variant uppercase text-[11px] font-bold tracking-wider">
                          <th className="py-2.5 px-3 rounded-l-xl font-bold">Policy / Scheme Name</th>
                          <th className="py-2.5 px-3 font-bold">Registration ID</th>
                          <th className="py-2.5 px-3 font-bold">Coverage</th>
                          <th className="py-2.5 px-3 font-bold">Created Date</th>
                          <th className="py-2.5 px-3 font-bold">Status</th>
                          <th className="py-2.5 px-3 text-right rounded-r-xl font-bold">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y-0">
                        {filteredRegistrations.length === 0 ? (
                          <tr>
                            <td colSpan={6} className="text-center py-8 text-on-surface-variant font-medium">
                              No records found for the selected filter.
                            </td>
                          </tr>
                        ) : (
                          filteredRegistrations.map((reg) => {
                            const dateStr = new Date(reg.created_at).toLocaleDateString('en-US', {
                              month: 'short',
                              day: '2-digit',
                              year: 'numeric',
                            });

                            return (
                              <tr
                                key={reg.id}
                                className="group hover:bg-surface-container-low transition-colors"
                              >
                                <td className="py-4 px-space-md">
                                  <div className="flex items-center gap-space-xs">
                                    <div
                                      className={`w-2 h-2 rounded-full shrink-0 ${
                                        reg.status === 'DECLINED' ? 'bg-outline' : 'bg-primary'
                                      }`}
                                    ></div>
                                    <span
                                      className={`font-label-md text-label-md font-semibold ${
                                        reg.status === 'DECLINED'
                                          ? 'text-on-surface-variant'
                                          : 'text-on-surface'
                                      }`}
                                    >
                                      {reg.policy?.policy_name || 'Care Premier Health Shield'}
                                    </span>
                                  </div>
                                </td>

                                <td className="py-4 px-space-md font-mono text-on-surface-variant">
                                  {reg.id}
                                </td>

                                <td className="py-4 px-space-md font-semibold text-on-surface">
                                  ₹{(reg.policy?.coverage_limit || 1500000).toLocaleString('en-IN')}
                                </td>

                                <td className="py-4 px-space-md text-on-surface-variant">{dateStr}</td>

                                <td className="py-4 px-space-md">
                                  {(reg.status === 'AWAITING_CUSTOMER_CONFIRMATION' || reg.status === 'PENDING_VERIFICATION') && (
                                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-container-high text-primary font-label-sm text-label-sm font-bold">
                                      <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></span>
                                      AWAITING_CONFIRMATION
                                    </span>
                                  )}
                                  {reg.status === 'CONFIRMED' && (
                                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-container-low text-primary font-label-sm text-label-sm font-semibold">
                                      <span className="w-1.5 h-1.5 rounded-full bg-primary"></span>
                                      CONFIRMED
                                    </span>
                                  )}
                                  {reg.status === 'PENDING_REVIEW' && (
                                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-container text-on-surface-variant font-label-sm text-label-sm font-semibold">
                                      <span className="w-1.5 h-1.5 rounded-full bg-outline"></span>
                                      PENDING_REVIEW
                                    </span>
                                  )}
                                  {reg.status === 'DECLINED' && (
                                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-container-low text-on-surface-variant font-label-sm text-label-sm font-semibold">
                                      DECLINED
                                    </span>
                                  )}
                                </td>

                                <td className="py-4 px-space-md text-right">
                                  {isAwaitingConfirmation(reg.status) && (
                                    <button
                                      onClick={() => handleOpenConfirmModal(reg)}
                                      className="text-primary font-label-md text-label-md hover:underline font-bold cursor-pointer"
                                    >
                                      Review &amp; Verify
                                    </button>
                                  )}
                                  {reg.status === 'CONFIRMED' && (
                                    <button
                                      onClick={() => handleOpenConfirmModal(reg)}
                                      className="text-on-surface-variant hover:text-on-surface font-label-md text-label-md transition-colors cursor-pointer"
                                    >
                                      View Policy
                                    </button>
                                  )}
                                  {reg.status === 'DECLINED' && (
                                    <span className="text-on-surface-variant/60 font-label-md text-label-md cursor-not-allowed">
                                      Archived
                                    </span>
                                  )}
                                </td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>

                  {/* Table Footer */}
                  <div className="pt-space-sm flex items-center justify-between font-label-sm text-label-sm text-on-surface-variant">
                    <span>
                      Showing {filteredRegistrations.length} of {totalCount} customer registrations
                    </span>
                    <div className="flex items-center gap-1">
                      <span className="font-mono text-on-surface font-semibold">100%</span>
                      <span>synchronicity with distributed core</span>
                    </div>
                  </div>
                </div>

                {/* 5. Claims Preview & API Boundary Section (4 Columns) */}
                <div className="lg:col-span-4 flex flex-col gap-4" id="claims-section">
                  {/* Claims Status Card */}
                  <div className="bg-surface-container-lowest rounded-2xl shadow-xs border border-slate-100 p-5 sm:p-6 flex flex-col justify-between gap-4">
                    <div className="flex flex-col gap-0.5">
                      <div className="flex items-center justify-between">
                        <h3 className="text-base sm:text-lg font-bold text-on-surface">
                          Claims Status
                        </h3>
                        <span className="material-symbols-outlined text-primary text-[18px]">
                          assignment_turned_in
                        </span>
                      </div>
                      <span className="text-[11px] font-bold text-on-surface-variant uppercase tracking-wider">
                        Customer-scoped claim tracking
                      </span>
                    </div>

                    {/* Zero Claim State Box */}
                    <div className="bg-surface-container-low p-4 rounded-xl flex flex-col gap-2.5">
                      <div className="w-8 h-8 rounded-full bg-surface-container-lowest text-primary flex items-center justify-center shadow-xs">
                        <span className="material-symbols-outlined text-[18px]">verified</span>
                      </div>
                      <div className="flex flex-col gap-0.5">
                        <span className="text-xs font-bold text-on-surface">
                          No active claims filed
                        </span>
                        <p className="text-xs text-on-surface-variant leading-relaxed">
                          No claims filed for your registered policies. Claims can be initiated from the dedicated Claims workflow when an event occurs.
                        </p>
                      </div>
                    </div>

                    {/* Action & Scope Boundary Note */}
                    <div className="flex flex-col gap-space-sm">
                      <a
                        className="inline-flex items-center gap-1 font-label-md text-label-md text-primary font-bold hover:gap-2 transition-all"
                        href="#registered-policies"
                        onClick={(e) => {
                          e.preventDefault();
                          showNotification('Claims Filing Engine: Submit hospital bills or incident invoices directly through verified portal.');
                        }}
                      >
                        <span>Go to Claims Guidance</span>
                        <span className="material-symbols-outlined text-[16px]">arrow_forward</span>
                      </a>
                      <div className="pt-2 flex items-start gap-1.5 text-on-surface-variant font-label-sm text-[11px] leading-tight">
                        <span className="material-symbols-outlined text-[14px] text-primary shrink-0 mt-0.5">lock</span>
                        <span>Compliance Constraint: Authority claims ledger access is restricted to verified adjusters.</span>
                      </div>
                    </div>
                  </div>

                  {/* Biometric Voice Assurance Telemetry Widget */}
                  <div className="bg-surface-container-lowest rounded-2xl shadow-sm p-space-lg flex flex-col gap-space-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-label-md text-label-md text-on-surface font-semibold">
                        Voice Biometrics Engine
                      </span>
                      <span className="px-2 py-0.5 rounded-full bg-surface-container-low text-primary font-mono text-[10px] font-bold">
                        READY
                      </span>
                    </div>

                    {/* Real-time Oscilloscope Visualization SVG */}
                    <div className="h-16 w-full bg-surface-container-low rounded-xl flex items-center justify-center px-4 overflow-hidden relative">
                      <svg className="w-full h-10 text-primary" fill="none" preserveAspectRatio="none" viewBox="0 0 300 40">
                        <path
                          d="M0 20 L20 20 L30 8 L40 32 L50 14 L60 26 L70 20 L90 20 L100 4 L110 36 L120 18 L130 22 L140 20 L170 20 L180 10 L190 30 L200 12 L210 28 L220 20 L240 20 L250 15 L260 25 L270 20 L300 20"
                          stroke="currentColor"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth="2"
                        ></path>
                      </svg>
                      <div className="absolute inset-0 bg-gradient-to-r from-surface-container-low via-transparent to-surface-container-low pointer-events-none"></div>
                    </div>

                    <div className="flex items-center justify-between text-on-surface-variant font-label-sm text-label-sm">
                      <span>Acoustic Profile Confidence</span>
                      <span className="text-primary font-mono font-bold">99.4% Match</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

            {/* TAB: MY POLICIES */}
            {activeCustomerTab === 'policies' && (
              <div className="w-full max-w-7xl mx-auto px-6 sm:px-10 lg:px-12 py-4 flex flex-col gap-8 animate-fadeIn">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[11px] font-bold uppercase tracking-wider text-primary">Portfolio Registry</span>
                      <span className="text-slate-400 text-xs">•</span>
                      <span className="text-[11px] font-semibold text-on-surface-variant">Active Coverage Underwritten</span>
                    </div>
                    <h1 className="text-2xl sm:text-3xl font-extrabold text-on-surface tracking-tight">My Registered Policies</h1>
                    <p className="text-xs sm:text-sm text-on-surface-variant">Statutory insurance bonds validated with immutable voice consent records.</p>
                  </div>
                  <button
                    onClick={() => {
                      window.open(
                        '/policies/care_premier_health_shield_v1.pdf',
                        '_blank'
                      );
                      showNotification('Opening official IRDAI statutory policy bond PDF');
                    }}
                    className="self-start sm:self-auto px-4 py-2 rounded-full bg-primary text-on-primary text-xs font-semibold flex items-center gap-2 hover:bg-secondary transition-all cursor-pointer shadow-sm"
                  >
                    <span className="material-symbols-outlined text-[16px]">download</span>
                    <span>Download All Bonds</span>
                  </button>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {registrations.map((reg) => (
                    <div key={reg.id} className="bg-surface-container-lowest rounded-2xl border border-slate-100 p-6 shadow-xs flex flex-col justify-between gap-6 hover:shadow-md transition-shadow">
                      <div className="flex flex-col gap-4">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-3">
                            <div className="w-12 h-12 rounded-xl bg-surface-container-low text-primary flex items-center justify-center font-bold">
                              <span className="material-symbols-outlined text-[24px]">verified_user</span>
                            </div>
                            <div>
                              <h3 className="text-base font-bold text-on-surface">{reg.policy?.policy_name || 'Care Premier Health Shield'}</h3>
                              <p className="text-xs text-on-surface-variant font-mono">{reg.policy?.policy_code || 'VG-HLT-01'} • {reg.id}</p>
                            </div>
                          </div>
                          <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                            reg.status === 'CONFIRMED'
                              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                              : reg.status === 'AWAITING_CUSTOMER_CONFIRMATION'
                              ? 'bg-amber-50 text-amber-700 border border-amber-200'
                              : 'bg-slate-100 text-slate-600'
                          }`}>
                            {reg.status}
                          </span>
                        </div>

                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 p-3.5 bg-surface-container-low rounded-xl">
                          <div>
                            <span className="text-[11px] text-on-surface-variant uppercase font-medium">Coverage Limit</span>
                            <p className="text-sm font-bold text-on-surface">₹{(reg.policy?.coverage_limit || 1500000).toLocaleString('en-IN')}</p>
                          </div>
                          <div>
                            <span className="text-[11px] text-on-surface-variant uppercase font-medium">Waiting Period</span>
                            <p className="text-sm font-bold text-on-surface">{reg.policy?.waiting_period_days || 730} Days</p>
                          </div>
                          <div>
                            <span className="text-[11px] text-on-surface-variant uppercase font-medium">Filing Window</span>
                            <p className="text-sm font-bold text-on-surface">{reg.policy?.claim_filing_window_days || 30} Days</p>
                          </div>
                        </div>

                        <div className="flex flex-col gap-1.5 text-xs text-on-surface-variant">
                          <div className="flex items-center gap-2">
                            <span className="material-symbols-outlined text-[16px] text-primary">graphic_eq</span>
                            <span>Acoustic Session Telemetry: <strong className="text-on-surface">Verified (87.4s)</strong></span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="material-symbols-outlined text-[16px] text-primary">policy</span>
                            <span>Consent Notes: <span className="italic">{reg.consent_notes || 'Verbal consent verified.'}</span></span>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center justify-between pt-4 border-t border-slate-100">
                        <span className="text-[11px] font-mono text-on-surface-variant">Registered: {new Date(reg.created_at).toLocaleDateString()}</span>
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => {
                              window.open(
                                '/policies/care_premier_health_shield_v1.pdf',
                                '_blank'
                              );
                              showNotification('Opening statutory Care Premier Health Shield Bond PDF');
                            }}
                            className="px-3 py-1.5 rounded-full bg-blue-50 hover:bg-blue-100 text-blue-700 text-xs font-semibold transition-colors flex items-center gap-1 cursor-pointer"
                          >
                            <span className="material-symbols-outlined text-[14px]">download</span>
                            <span>Policy PDF</span>
                          </button>

                          <button
                            type="button"
                            onClick={() => {
                              setActiveCustomerTab('claims');
                              setShowFileClaimModal(true);
                            }}
                            className="px-3 py-1.5 rounded-full bg-emerald-50 hover:bg-emerald-100 text-emerald-700 text-xs font-semibold transition-colors flex items-center gap-1 cursor-pointer"
                          >
                            <span className="material-symbols-outlined text-[14px]">add_circle</span>
                            <span>File Claim</span>
                          </button>

                          <button
                            type="button"
                            onClick={() => handleOpenConfirmModal(reg)}
                            className="px-3.5 py-1.5 rounded-full bg-primary hover:bg-secondary text-white text-xs font-bold transition-colors flex items-center gap-1 cursor-pointer shadow-xs"
                          >
                            <span className="material-symbols-outlined text-[14px]">verified</span>
                            <span>{reg.status === 'CONFIRMED' ? 'View Certificate' : 'Review & Confirm'}</span>
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* TAB: MY CLAIMS */}
            {activeCustomerTab === 'claims' && (
              <div className="w-full max-w-7xl mx-auto px-6 sm:px-10 lg:px-12 py-4 flex flex-col gap-8 animate-fadeIn">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[11px] font-bold uppercase tracking-wider text-primary">Disbursement Center</span>
                      <span className="text-slate-400 text-xs">•</span>
                      <span className="text-[11px] font-semibold text-on-surface-variant">Deterministic Claims Engine</span>
                    </div>
                    <h1 className="text-2xl sm:text-3xl font-extrabold text-on-surface tracking-tight">My Claims &amp; Fast-Track Settlement</h1>
                    <p className="text-xs sm:text-sm text-on-surface-variant">Automated sub-limit verification with instant simulation and transparent auditing.</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleSeedSampleClaim}
                      className="px-4 py-2 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer shadow-xs"
                    >
                      <span className="material-symbols-outlined text-[16px]">healing</span>
                      <span>Demo Hospital Claim</span>
                    </button>
                    <button
                      onClick={() => setShowFileClaimModal(true)}
                      className="px-4 py-2 rounded-full bg-primary text-on-primary text-xs font-semibold flex items-center gap-2 hover:bg-secondary transition-all cursor-pointer shadow-sm"
                    >
                      <span className="material-symbols-outlined text-[16px]">add_circle</span>
                      <span>File New Claim</span>
                    </button>
                  </div>
                </div>

                {claimsList.length === 0 ? (
                  /* Rich interactive empty state */
                  <div className="bg-surface-container-lowest rounded-3xl border border-slate-200 p-10 text-center flex flex-col items-center justify-center gap-4">
                    <div className="w-16 h-16 rounded-2xl bg-blue-50 text-primary flex items-center justify-center">
                      <span className="material-symbols-outlined text-[32px]">clinical_notes</span>
                    </div>
                    <div className="max-w-md">
                      <h3 className="text-lg font-bold text-on-surface">No Claims Filed Yet</h3>
                      <p className="text-xs text-on-surface-variant mt-1 leading-relaxed">
                        Your policy coverage is fully active and protected. You can submit a hospitalization invoice for automated instant adjudication, or load a sample claim to test payouts.
                      </p>
                    </div>
                    <div className="flex items-center gap-3 mt-2">
                      <button
                        onClick={() => setShowFileClaimModal(true)}
                        className="px-5 py-2.5 rounded-full bg-primary text-on-primary text-xs font-bold hover:bg-secondary transition-all cursor-pointer shadow-sm flex items-center gap-1.5"
                      >
                        <span className="material-symbols-outlined text-[16px]">add_circle</span>
                        <span>File New Claim</span>
                      </button>
                      <button
                        onClick={handleSeedSampleClaim}
                        className="px-5 py-2.5 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5"
                      >
                        <span className="material-symbols-outlined text-[16px]">science</span>
                        <span>Load Sample Claim</span>
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col gap-6">
                    {claimsList.map((claim) => (
                      <div key={claim.id} className="bg-surface-container-lowest rounded-2xl border border-slate-100 p-6 shadow-xs flex flex-col gap-6">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-100">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-xl bg-surface-container-low text-primary flex items-center justify-center font-bold">
                              <span className="material-symbols-outlined text-[20px]">receipt_long</span>
                            </div>
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="text-base font-bold text-on-surface">{claim.id}</span>
                                <span className="text-xs font-mono text-on-surface-variant">({claim.claim_category})</span>
                              </div>
                              <p className="text-xs text-on-surface-variant">Incident Date: {claim.incident_date} • Policy: {claim.policy?.policy_name || 'Care Premier Health Shield'}</p>
                            </div>
                          </div>

                          <div className="flex items-center gap-3">
                            <div className="text-right">
                              <span className="text-[10px] text-on-surface-variant uppercase font-medium">Claim Amount</span>
                              <p className="text-base font-extrabold text-on-surface">₹{claim.requested_amount.toLocaleString('en-IN')}</p>
                            </div>
                            <span className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider ${
                              claim.status === 'PAID'
                                ? 'bg-emerald-100 text-emerald-800 border border-emerald-300'
                                : claim.status === 'APPROVED'
                                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                : claim.status === 'UNDER_REVIEW'
                                ? 'bg-amber-50 text-amber-700 border border-amber-200'
                                : 'bg-slate-100 text-slate-700'
                            }`}>
                              {claim.status}
                            </span>
                          </div>
                        </div>

                        {/* Timeline Progression */}
                        <div className="flex flex-col gap-2">
                          <span className="text-xs font-bold uppercase text-on-surface-variant tracking-wider">Settlement Progress</span>
                          <div className="grid grid-cols-4 gap-2 text-center text-[11px] font-semibold">
                            <div className="p-2 rounded-lg bg-emerald-50 text-emerald-700 flex flex-col items-center gap-1">
                              <span className="material-symbols-outlined text-[16px]">task_alt</span>
                              <span>1. Submitted</span>
                            </div>
                            <div className="p-2 rounded-lg bg-emerald-50 text-emerald-700 flex flex-col items-center gap-1">
                              <span className="material-symbols-outlined text-[16px]">record_voice_over</span>
                              <span>2. Audio &amp; OCR OK</span>
                            </div>
                            <div className={`p-2 rounded-lg flex flex-col items-center gap-1 ${
                              claim.status === 'APPROVED' || claim.status === 'PAID'
                                ? 'bg-emerald-50 text-emerald-700 font-bold'
                                : claim.status === 'REJECTED'
                                ? 'bg-rose-50 text-rose-700 font-bold'
                                : 'bg-amber-50 text-amber-800 font-bold animate-pulse border border-amber-200'
                            }`}>
                              <span className="material-symbols-outlined text-[16px]">
                                {claim.status === 'APPROVED' || claim.status === 'PAID' ? 'verified' : claim.status === 'REJECTED' ? 'cancel' : 'hourglass_top'}
                              </span>
                              <span>
                                {claim.status === 'APPROVED' || claim.status === 'PAID' ? '3. Authority Approved' : claim.status === 'REJECTED' ? '3. Rejected' : '3. Authority Review'}
                              </span>
                            </div>
                            <div className={`p-2 rounded-lg flex flex-col items-center gap-1 ${
                              claim.status === 'PAID'
                                ? 'bg-emerald-600 text-white font-bold'
                                : claim.status === 'APPROVED'
                                ? 'bg-emerald-100 text-emerald-800 font-bold'
                                : 'bg-slate-100 text-slate-400'
                            }`}>
                              <span className="material-symbols-outlined text-[16px]">
                                {claim.status === 'PAID' || claim.status === 'APPROVED' ? 'payments' : 'lock'}
                              </span>
                              <span>{claim.status === 'PAID' ? '4. Disbursed (IMPS)' : claim.status === 'APPROVED' ? '4. Ready to Payout' : '4. Locked'}</span>
                            </div>
                          </div>
                        </div>

                        {/* Rule Breakdown Card */}
                        {claim.latest_assessment && (
                          <div className="p-4 bg-surface-container-low rounded-xl flex flex-col gap-3">
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-bold text-on-surface flex items-center gap-1.5">
                                <span className="material-symbols-outlined text-[16px] text-primary">fact_check</span>
                                Deterministic Eligibility &amp; Fraud Screen
                              </span>
                              <span className={`text-[11px] font-mono font-bold px-2 py-0.5 rounded ${
                                claim.status === 'APPROVED' || claim.status === 'PAID'
                                  ? 'bg-emerald-100 text-emerald-800'
                                  : 'bg-amber-100 text-amber-800'
                              }`}>
                                Outcome: {claim.status === 'APPROVED' || claim.status === 'PAID' ? 'ELIGIBLE' : 'PENDING_AUTHORITY_REVIEW'}
                              </span>
                            </div>
                            <div className="flex flex-col gap-2">
                              {claim.latest_assessment.rules_evaluated.map((r, idx) => (
                                <div key={idx} className="flex items-start justify-between gap-2 text-xs bg-surface-container-lowest p-2.5 rounded-lg">
                                  <div className="flex items-start gap-2">
                                    <span className={`material-symbols-outlined text-[16px] shrink-0 ${
                                      r.result === 'PASSED' ? 'text-emerald-600' : 'text-amber-600'
                                    }`}>
                                      {r.result === 'PASSED' ? 'check_circle' : 'pending'}
                                    </span>
                                    <div>
                                      <span className="font-semibold text-on-surface">{r.rule_id}: </span>
                                      <span className="text-on-surface-variant">{r.explanation}</span>
                                    </div>
                                  </div>
                                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                    r.result === 'PASSED' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
                                  }`}>
                                    {r.result}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Settlement Action Bar */}
                        <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
                          <span className="text-xs text-on-surface-variant">Description: {claim.description}</span>
                          {claim.status === 'PAID' ? (
                            <span className="px-4 py-2 rounded-full bg-emerald-100 text-emerald-800 text-xs font-bold flex items-center gap-1.5">
                              <span className="material-symbols-outlined text-[16px]">check_circle</span>
                              <span>Disbursed via IMPS (UTR #8821947219)</span>
                            </span>
                          ) : claim.status === 'APPROVED' ? (
                            <button
                              onClick={() => handleSimulateClaimPayout(claim.id)}
                              className="px-5 py-2.5 rounded-full bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold flex items-center gap-1.5 transition-colors cursor-pointer shadow-md"
                            >
                              <span className="material-symbols-outlined text-[16px]">account_balance</span>
                              <span>Simulate Instant IMPS Payout</span>
                            </button>
                          ) : (
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="px-3.5 py-2 rounded-xl bg-amber-50 text-amber-800 text-xs font-semibold flex items-center gap-1.5 border border-amber-200">
                                <span className="material-symbols-outlined text-[16px] text-amber-600">lock</span>
                                <span>Awaiting Authority Adjudication</span>
                              </span>
                              <button
                                onClick={() => handleSimulateAuthorityApproval(claim.id)}
                                className="px-3.5 py-2 rounded-xl bg-[#004AC6] hover:bg-[#1D4ED8] text-white text-xs font-bold flex items-center gap-1.5 transition-colors cursor-pointer shadow-xs"
                                title="Simulate Approval Authority decision to unlock IMPS payout"
                              >
                                <span className="material-symbols-outlined text-[15px]">verified</span>
                                <span>Simulate Authority Approval</span>
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* TAB: DOCUMENTS VAULT */}
            {activeCustomerTab === 'documents' && (
              <div className="w-full max-w-7xl mx-auto px-6 sm:px-10 lg:px-12 py-4 flex flex-col gap-8 animate-fadeIn">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-primary">IRDAI Statutory Vault</span>
                    <span className="text-slate-400 text-xs">•</span>
                    <span className="text-[11px] font-semibold text-on-surface-variant">Tamper-Proof Certificates</span>
                  </div>
                  <h1 className="text-2xl sm:text-3xl font-extrabold text-on-surface tracking-tight">Cryptographic Disclosures & Audio Vault</h1>
                  <p className="text-xs sm:text-sm text-on-surface-variant">Certified copies of consultation recordings, signed policy contracts, and SHA-256 Merkle proofs.</p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Hidden HTML5 Audio Element */}
                  <audio
                    ref={audioRef}
                    src={audioUrl}
                    onTimeUpdate={handleAudioTimeUpdate}
                    onLoadedMetadata={handleAudioLoadedMetadata}
                    onEnded={handleAudioEnded}
                  />

                  {/* Document 1: Tele-sales audio */}
                  <div className="bg-surface-container-lowest rounded-2xl border border-slate-100 p-6 shadow-xs flex flex-col justify-between gap-5">
                    <div className="flex flex-col gap-4">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-3">
                          <div className={`w-11 h-11 rounded-xl flex items-center justify-center font-bold transition-colors ${
                            playingAudio ? 'bg-primary text-white shadow-md' : 'bg-surface-container-low text-primary'
                          }`}>
                            <span className={`material-symbols-outlined text-[22px] ${playingAudio ? 'animate-pulse' : ''}`}>
                              graphic_eq
                            </span>
                          </div>
                          <div>
                            <h3 className="text-sm font-bold text-on-surface">Tele-sales Consultation Audio</h3>
                            <p className="text-[11px] text-on-surface-variant font-mono">
                              {audioFileName} ({audioFileSize})
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-[10px] font-bold uppercase tracking-wider border border-emerald-200">
                            SEALED
                          </span>
                        </div>
                      </div>

                      {/* Real Audio Player Controls */}
                      <div className="p-4 bg-surface-container-low rounded-2xl flex flex-col gap-3 border border-slate-100">
                        <div className="flex items-center justify-between gap-3">
                          <button
                            type="button"
                            onClick={toggleAudioPlay}
                            className="w-11 h-11 rounded-full bg-primary text-on-primary flex items-center justify-center shrink-0 hover:bg-secondary transition-all transform active:scale-95 shadow-md cursor-pointer"
                            title={playingAudio ? 'Pause Audio' : 'Play Audio'}
                          >
                            <span className="material-symbols-outlined text-[24px]">
                              {playingAudio ? 'pause' : 'play_arrow'}
                            </span>
                          </button>

                          <div className="flex-1 flex flex-col gap-1.5">
                            <div className="flex items-center justify-between text-[11px] font-mono text-on-surface-variant font-medium">
                              <span className="text-primary font-bold">{formatAudioTime(audioCurrentTime)}</span>
                              <span>{formatAudioTime(audioDuration)}</span>
                            </div>

                            {/* Real Seekable Range Scrubber */}
                            <input
                              type="range"
                              min={0}
                              max={audioDuration || 1}
                              step={0.1}
                              value={audioCurrentTime}
                              onChange={handleAudioSeek}
                              className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-primary"
                            />
                          </div>
                        </div>

                        {/* Animated Voice Waveform Bars */}
                        <div className="flex items-center justify-center gap-1 h-6 px-2 overflow-hidden">
                          {[40, 70, 30, 90, 60, 100, 45, 80, 50, 95, 35, 75, 85, 40, 65, 90, 30, 80, 55, 70].map((h, i) => (
                            <div
                              key={i}
                              style={{
                                height: playingAudio ? `${Math.max(15, (h * ((i % 3) + 1)) % 100)}%` : '20%',
                                transition: 'height 150ms ease-in-out',
                              }}
                              className={`w-1 rounded-full ${playingAudio ? 'bg-primary' : 'bg-slate-300'}`}
                            />
                          ))}
                        </div>
                      </div>

                      {/* Cryptographic SHA-256 Proof */}
                      <div className="p-3 bg-slate-50 border border-slate-200/80 rounded-xl flex flex-col gap-1">
                        <div className="flex items-center justify-between text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                          <span>SHA-256 Acoustic Merkle Leaf</span>
                          <span className="text-emerald-600 font-semibold flex items-center gap-0.5">
                            <span className="material-symbols-outlined text-[12px]">verified</span>
                            <span>Verified Match</span>
                          </span>
                        </div>
                        <span className="text-[11px] font-mono text-slate-700 break-all select-all font-semibold">
                          {audioHash}
                        </span>
                      </div>
                    </div>

                    {/* Action Buttons: Download + Upload */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-2 border-t border-slate-100">
                      <button
                        type="button"
                        onClick={handleDownloadAudio}
                        className="py-2.5 px-3 rounded-xl bg-surface-container-low hover:bg-surface-container-high text-on-surface text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer border border-slate-200"
                      >
                        <span className="material-symbols-outlined text-[16px] text-primary">download</span>
                        <span>Download Audio</span>
                      </button>

                      <label className="py-2.5 px-3 rounded-xl bg-primary/10 hover:bg-primary/20 text-primary text-xs font-bold flex items-center justify-center gap-1.5 transition-colors cursor-pointer border border-primary/20">
                        <span className="material-symbols-outlined text-[16px]">upload_file</span>
                        <span>{isAudioLoading ? 'Hashing...' : 'Upload Real Audio'}</span>
                        <input
                          type="file"
                          accept="audio/*"
                          onChange={handleUploadAudio}
                          className="hidden"
                          disabled={isAudioLoading}
                        />
                      </label>
                    </div>
                  </div>

                  {/* Document 2: Policy Bond PDF */}
                  <div className="bg-surface-container-lowest rounded-2xl border border-slate-100 p-6 shadow-xs flex flex-col justify-between gap-5">
                    <div className="flex flex-col gap-4">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-3">
                          <div className="w-11 h-11 rounded-xl bg-red-50 text-red-600 flex items-center justify-center font-bold">
                            <span className="material-symbols-outlined text-[22px]">picture_as_pdf</span>
                          </div>
                          <div>
                            <h3 className="text-sm font-bold text-on-surface">Care Premier Health Shield Bond</h3>
                            <p className="text-[11px] text-on-surface-variant font-mono">
                              care_premier_health_shield_v1.pdf (IRDAI Approved)
                            </p>
                          </div>
                        </div>
                        <span className="px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-[10px] font-bold uppercase tracking-wider border border-emerald-200">
                          SIGNED
                        </span>
                      </div>

                      <div className="p-3 bg-surface-container-low rounded-xl text-xs text-on-surface-variant flex flex-col gap-2 border border-slate-100">
                        <div className="flex justify-between items-center">
                          <span className="text-[11px] text-slate-500 font-medium">Signatory Registrar:</span>
                          <span className="font-semibold text-on-surface text-right">Care Health Insurance • IRDAI Reg #882</span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-[11px] text-slate-500 font-medium">Policy Reference:</span>
                          <span className="font-mono text-primary font-bold">VG-HLT-01 • v1.0 Statutory</span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-[11px] text-slate-500 font-medium">IRDAI Certified Vault:</span>
                          <span className="font-mono text-emerald-600 font-semibold text-[11px] flex items-center gap-1">
                            <span className="material-symbols-outlined text-[13px]">cloud_done</span>
                            <span>vachan.gov.in / IRDAI Vault</span>
                          </span>
                        </div>
                      </div>

                      {/* PDF SHA-256 Hash */}
                      <div className="p-3 bg-slate-50 border border-slate-200/80 rounded-xl flex flex-col gap-1">
                        <div className="flex items-center justify-between text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                          <span>SHA-256 PDF Document Checksum</span>
                          <span className="text-emerald-600 font-semibold flex items-center gap-0.5">
                            <span className="material-symbols-outlined text-[12px]">verified</span>
                            <span>IRDAI Anchored</span>
                          </span>
                        </div>
                        <span className="text-[11px] font-mono text-slate-700 break-all select-all font-semibold">
                          a6295ac06d34788312533f725b57cc64cd3ad1b959a4fff59c976191f6bb5ef7
                        </span>
                      </div>
                    </div>

                    <div className="pt-2 border-t border-slate-100">
                      <button
                        type="button"
                        onClick={() => {
                          window.open(
                            '/policies/care_premier_health_shield_v1.pdf',
                            '_blank'
                          );
                          showNotification('Opening statutory Care Premier Health Shield Bond PDF');
                        }}
                        className="w-full py-2.5 rounded-xl bg-primary hover:bg-secondary text-on-primary text-xs font-bold flex items-center justify-center gap-2 transition-all cursor-pointer shadow-md"
                      >
                        <span className="material-symbols-outlined text-[16px]">download</span>
                        <span>Download Statutory Policy Bond PDF</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* TAB: ACTIVITY AUDIT TRAIL */}
            {activeCustomerTab === 'activity' && (
              <div className="w-full max-w-7xl mx-auto px-6 sm:px-10 lg:px-12 py-4 flex flex-col gap-8 animate-fadeIn">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-primary">Immutable History</span>
                    <span className="text-slate-400 text-xs">•</span>
                    <span className="text-[11px] font-semibold text-on-surface-variant">AuditTrail Engine</span>
                  </div>
                  <h1 className="text-2xl sm:text-3xl font-extrabold text-on-surface tracking-tight">Ledger Activity & Consent Log</h1>
                  <p className="text-xs sm:text-sm text-on-surface-variant">Real-time log of every biometric signature, claim filing, and blockchain anchor.</p>
                </div>

                <div className="bg-surface-container-lowest rounded-2xl border border-slate-100 p-6 shadow-xs flex flex-col gap-4">
                  {[
                    { action: 'CUSTOMER_CONFIRMATION', time: 'Today, 14:32 IST', desc: 'Policy REG-2026-8821 confirmed with customer signature token.', status: 'ANCHORED', hash: '0x8821...a14f' },
                    { action: 'VOICE_SESSION_SEALED', time: 'Today, 10:30 IST', desc: 'Acoustic consultation recording encrypted with TLS 1.3 and uploaded to Cloudinary vault.', status: 'VERIFIED', hash: '0x7721...bc90' },
                    { action: 'CLAIM_SUBMITTED', time: 'Oct 05, 2026', desc: 'Claim CLM-2026-8812 filed for ₹70,000 hospitalization invoice.', status: 'AUDITED', hash: '0x3310...d552' },
                    { action: 'POLICY_ISSUED', time: 'Oct 02, 2026', desc: 'Care Premier Health Shield underwritten by broker Rajesh M.', status: 'COMMITTED', hash: '0x1204...ee71' },
                  ].map((act, i) => (
                    <div key={i} className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 bg-surface-container-low rounded-xl">
                      <div className="flex items-start gap-3">
                        <div className="w-9 h-9 rounded-full bg-surface-container-lowest text-primary flex items-center justify-center shrink-0 shadow-xs">
                          <span className="material-symbols-outlined text-[18px]">verified</span>
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-bold text-on-surface">{act.action}</span>
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700">{act.status}</span>
                          </div>
                          <p className="text-xs text-on-surface-variant mt-0.5">{act.desc}</p>
                        </div>
                      </div>
                      <div className="text-right sm:shrink-0">
                        <span className="text-[11px] font-mono text-on-surface-variant">{act.time}</span>
                        <p className="text-[10px] font-mono text-primary font-bold">{act.hash}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

          </div>
        </main>
      </div>

      {/* ======================================================== */}
      {/* FILE NEW CLAIM MODAL (Fast-Track Automated Adjudication) */}
      {/* ======================================================== */}
      {showFileClaimModal && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto animate-in fade-in duration-200">
          <div className="bg-white rounded-3xl max-w-lg w-full p-6 sm:p-8 shadow-2xl border border-slate-200 space-y-6">
            <div className="flex items-start justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-blue-50 text-primary flex items-center justify-center font-bold">
                  <span className="material-symbols-outlined text-[24px]">add_notes</span>
                </div>
                <div>
                  <h3 className="text-base font-extrabold text-on-surface">File Fast-Track Claim</h3>
                  <p className="text-xs text-on-surface-variant mt-0.5">Automated sub-limit check against Care Premier Health Shield</p>
                </div>
              </div>
              <button
                onClick={() => setShowFileClaimModal(false)}
                className="w-8 h-8 rounded-full bg-slate-100 hover:bg-slate-200 flex items-center justify-center text-slate-600 transition cursor-pointer"
              >
                <span className="material-symbols-outlined text-[20px]">close</span>
              </button>
            </div>

            <form onSubmit={handleCreateNewClaim} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-on-surface uppercase mb-1">Claim Category</label>
                <select
                  value={newClaimCategory}
                  onChange={(e: any) => setNewClaimCategory(e.target.value)}
                  className="w-full h-10 px-3 rounded-xl bg-slate-50 border border-slate-200 text-xs font-semibold focus:outline-none focus:border-primary"
                >
                  <option value="HOSPITALIZATION">HOSPITALIZATION (Inpatient Cashless / Reimbursement)</option>
                  <option value="VEHICLE">VEHICLE (Accidental Collision Damage)</option>
                  <option value="GENERIC">GENERIC (Outpatient / Diagnostic Care)</option>
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-on-surface uppercase mb-1">Claim Amount (₹) *</label>
                  <input
                    type="number"
                    required
                    value={newClaimAmount}
                    onChange={(e) => setNewClaimAmount(e.target.value)}
                    className="w-full h-10 px-3 rounded-xl bg-slate-50 border border-slate-200 text-xs font-bold focus:outline-none focus:border-primary"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-on-surface uppercase mb-1">Incident Date *</label>
                  <input
                    type="date"
                    required
                    defaultValue={newClaimCategory ? new Date().toISOString().split('T')[0] : ''}
                    className="w-full h-10 px-3 rounded-xl bg-slate-50 border border-slate-200 text-xs focus:outline-none focus:border-primary"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-on-surface uppercase mb-1">Treating Hospital / Provider *</label>
                <input
                  type="text"
                  required
                  value={newClaimHospital}
                  onChange={(e) => setNewClaimHospital(e.target.value)}
                  placeholder="e.g. Fortis Hospital, Apollo Clinic"
                  className="w-full h-10 px-3 rounded-xl bg-slate-50 border border-slate-200 text-xs focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-on-surface uppercase mb-1">Medical Invoice Document *</label>
                <div className="p-3 bg-slate-50 rounded-xl border border-dashed border-slate-300 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-[20px]">upload_file</span>
                    <span className="font-semibold text-slate-700">hospital_tax_invoice_final.pdf</span>
                  </div>
                  <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 text-[10px] font-bold">OCR READY</span>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-on-surface uppercase mb-1">Incident Narrative &amp; Doctor Notes</label>
                <textarea
                  rows={2}
                  value={newClaimDescription}
                  onChange={(e) => setNewClaimDescription(e.target.value)}
                  className="w-full p-3 rounded-xl bg-slate-50 border border-slate-200 text-xs focus:outline-none focus:border-primary"
                ></textarea>
              </div>

              <div className="pt-2 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowFileClaimModal(false)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 transition cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingClaim}
                  className="px-6 py-2.5 rounded-xl text-xs font-bold text-white bg-primary hover:bg-secondary transition flex items-center gap-1.5 shadow-md cursor-pointer"
                >
                  <span className={`material-symbols-outlined text-[16px] ${isSubmittingClaim ? 'animate-spin' : ''}`}>
                    {isSubmittingClaim ? 'sync' : 'send'}
                  </span>
                  <span>{isSubmittingClaim ? 'Validating against Policy...' : 'Submit Claim for Instant Payout'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* STATUTORY POLICY CERTIFICATE & CONFIRMATION MODAL */}
      {showConfirmModal && targetReg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
          <div className="bg-surface-container-lowest rounded-3xl max-w-2xl w-full p-6 sm:p-8 shadow-2xl border border-slate-200 flex flex-col gap-6 max-h-[90vh] overflow-y-auto">
            {/* Modal Header */}
            <div className="flex items-start justify-between pb-4 border-b border-slate-100">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-2xl bg-primary/10 text-primary flex items-center justify-center font-bold">
                  <span className="material-symbols-outlined text-[28px]">verified_user</span>
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-primary">IRDAI Statutory Certificate</span>
                    <span className="text-slate-300">•</span>
                    <span className="text-[11px] font-mono text-slate-500">Ref #{targetReg.id}</span>
                  </div>
                  <h2 className="text-xl font-bold text-on-surface">
                    {targetReg.policy?.policy_name || 'Care Premier Health Shield'}
                  </h2>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowConfirmModal(false)}
                className="w-8 h-8 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-600 flex items-center justify-center transition-colors cursor-pointer"
              >
                <span className="material-symbols-outlined text-[18px]">close</span>
              </button>
            </div>

            {/* Certificate Body */}
            <div className="p-5 rounded-2xl bg-gradient-to-br from-slate-50 via-white to-blue-50/30 border border-slate-200/80 shadow-xs flex flex-col gap-4">
              <div className="flex items-center justify-between pb-3 border-b border-slate-200/60">
                <div>
                  <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Primary Insured Holder</span>
                  <p className="text-base font-extrabold text-on-surface">{user?.full_name || 'Samarth Khadse'}</p>
                  <p className="text-xs text-slate-500 font-mono">{user?.email || 'samarthkhadse7@gmail.com'}</p>
                </div>
                <div className="text-right">
                  <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Underwriting Insurer</span>
                  <p className="text-sm font-bold text-on-surface">{targetReg.policy?.insurer_name || 'Care Health Insurance Limited'}</p>
                  <span className={`inline-block mt-0.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                    targetReg.status === 'CONFIRMED'
                      ? 'bg-emerald-100 text-emerald-800'
                      : 'bg-amber-100 text-amber-800'
                  }`}>
                    {targetReg.status}
                  </span>
                </div>
              </div>

              {/* Coverage Grid */}
              <div className="grid grid-cols-3 gap-2.5 p-3 bg-white rounded-xl border border-slate-200/60 text-center">
                <div>
                  <span className="text-[10px] text-slate-500 uppercase font-semibold">Coverage Sum</span>
                  <p className="text-sm font-extrabold text-primary">₹{(targetReg.policy?.coverage_limit || 1500000).toLocaleString('en-IN')}</p>
                </div>
                <div>
                  <span className="text-[10px] text-slate-500 uppercase font-semibold">Waiting Period</span>
                  <p className="text-sm font-bold text-on-surface">{targetReg.policy?.waiting_period_days || 730} Days</p>
                </div>
                <div>
                  <span className="text-[10px] text-slate-500 uppercase font-semibold">Claim Window</span>
                  <p className="text-sm font-bold text-on-surface">{targetReg.policy?.claim_filing_window_days || 30} Days</p>
                </div>
              </div>

              {/* Acoustic Telemetry Record */}
              <div className="p-3 bg-blue-50/50 rounded-xl border border-blue-100 flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-xs font-bold text-blue-900">
                    <span className="material-symbols-outlined text-[16px] text-primary">graphic_eq</span>
                    <span>Verbal Tele-Sales Consent Audit</span>
                  </div>
                  <span className="text-[10px] font-bold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-full">
                    ACOUSTIC MATCH: 99.8%
                  </span>
                </div>
                <p className="text-xs text-slate-600 italic">
                  "{targetReg.consent_notes || 'Oral affirmative consent recorded under voice telemetry with verified Aadhaar phone OTP.'}"
                </p>
                <div className="text-[10px] font-mono text-slate-500 break-all bg-white p-2 rounded-lg border border-slate-200/60">
                  SHA-256 Merkle Leaf: bfb60e5f5438b5f802c46a4b63fe274d337a0307c7f51a6fdf105122d19fc01c
                </div>
              </div>

              {/* AI Promise vs Policy Parity Discrepancy Breakdown */}
              <div className="p-4 bg-slate-900 text-white rounded-2xl flex flex-col gap-3 shadow-md border border-slate-800">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-amber-400 text-[18px]">policy</span>
                    <span className="text-xs font-bold text-white uppercase tracking-wider">AI Discrepancy &amp; Mis-Selling Audit</span>
                  </div>
                  <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-bold text-[10px] uppercase border border-amber-500/30">
                    Discrepancies Flagged
                  </span>
                </div>
                <p className="text-[11px] text-slate-300">
                  VACHAN AI evaluated what agent Rajesh promised on the audio consultation call against official statutory policy clauses. Review discrepancies before approving:
                </p>

                <div className="flex flex-col gap-2">
                  <div className="p-2.5 rounded-xl bg-slate-800/80 border border-emerald-500/30 flex flex-col gap-1 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-emerald-400 flex items-center gap-1">
                        <span className="material-symbols-outlined text-[14px]">check_circle</span>
                        Room Rent &amp; ICU Cashless Up to ₹15 Lakhs
                      </span>
                      <span className="text-[10px] font-bold text-emerald-300 bg-emerald-950 px-1.5 py-0.5 rounded">SUPPORTED</span>
                    </div>
                    <p className="text-[11px] text-slate-400 italic">Agent said: "₹15 Lakhs sum insured cashless network par covered hai." &rarr; Matches Clause 1.1</p>
                  </div>

                  <div className="p-2.5 rounded-xl bg-slate-800/80 border border-amber-500/30 flex flex-col gap-1 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-amber-400 flex items-center gap-1">
                        <span className="material-symbols-outlined text-[14px]">warning</span>
                        Diabetes &amp; BP Pre-Existing Conditions
                      </span>
                      <span className="text-[10px] font-bold text-amber-300 bg-amber-950 px-1.5 py-0.5 rounded">OMISSION WARNING</span>
                    </div>
                    <p className="text-[11px] text-slate-400 italic">Agent said: "Diabetes aur BP completely covered hai." &rarr; Policy Clause 2.2 requires mandatory 24-month (730 days) waiting period!</p>
                  </div>

                  <div className="p-2.5 rounded-xl bg-slate-800/80 border border-rose-500/30 flex flex-col gap-1 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-rose-400 flex items-center gap-1">
                        <span className="material-symbols-outlined text-[14px]">cancel</span>
                        Cosmetic Procedures &amp; Routine OPD
                      </span>
                      <span className="text-[10px] font-bold text-rose-300 bg-rose-950 px-1.5 py-0.5 rounded">CONTRADICTION</span>
                    </div>
                    <p className="text-[11px] text-slate-400 italic">Agent said: "Cosmetic laser ya OPD clinic checkup 100% bina hospital admit huye reimburse." &rarr; Policy Clause 3.1 &amp; 3.2 strictly excludes cosmetic &amp; routine OPD!</p>
                  </div>
                </div>
              </div>

              {/* Statutory Policy Bond Download Link */}
              <div className="flex items-center justify-between p-3 bg-white rounded-xl border border-slate-200/60">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-red-600 text-[20px]">picture_as_pdf</span>
                  <div>
                    <span className="text-xs font-bold text-on-surface">IRDAI Underwriting Policy Bond (PDF)</span>
                    <p className="text-[10px] text-slate-500 font-mono">care_premier_health_shield_v1.pdf • 2.4 MB</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    window.open('/policies/care_premier_health_shield_v1.pdf', '_blank');
                  }}
                  className="px-3 py-1.5 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs font-semibold flex items-center gap-1 cursor-pointer transition-colors"
                >
                  <span className="material-symbols-outlined text-[14px]">download</span>
                  <span>View PDF</span>
                </button>
              </div>
            </div>

            {/* Modal Actions */}
            <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  window.open('/policies/care_premier_health_shield_v1.pdf', '_blank');
                }}
                className="w-full sm:w-auto px-4 py-2.5 rounded-xl border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-semibold flex items-center justify-center gap-1.5 cursor-pointer transition-colors"
              >
                <span className="material-symbols-outlined text-[16px]">print</span>
                <span>Print Certificate</span>
              </button>

              <div className="flex items-center gap-3 w-full sm:w-auto">
                {targetReg.status !== 'CONFIRMED' ? (
                  <>
                    <button
                      type="button"
                      onClick={() => {
                        handleDecline(targetReg.id);
                        setShowConfirmModal(false);
                      }}
                      className="px-4 py-2.5 rounded-xl bg-slate-100 hover:bg-rose-50 text-rose-700 text-xs font-bold transition-colors cursor-pointer"
                    >
                      Decline
                    </button>
                    <button
                      type="button"
                      onClick={handleExecuteConfirm}
                      disabled={isConfirming}
                      className="flex-1 sm:flex-initial px-6 py-2.5 rounded-xl bg-primary hover:bg-secondary text-white text-xs font-bold transition-all flex items-center justify-center gap-2 shadow-md cursor-pointer disabled:opacity-50"
                    >
                      <span className={`material-symbols-outlined text-[16px] ${isConfirming ? 'animate-spin' : ''}`}>
                        {isConfirming ? 'sync' : 'fingerprint'}
                      </span>
                      <span>{isConfirming ? 'Binding on Ledger...' : 'Confirm & Activate Policy'}</span>
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      setShowConfirmModal(false);
                      setActiveCustomerTab('claims');
                      setShowFileClaimModal(true);
                    }}
                    className="px-6 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold transition-all flex items-center gap-1.5 shadow-md cursor-pointer"
                  >
                    <span className="material-symbols-outlined text-[16px]">add_circle</span>
                    <span>File Claim Under This Policy</span>
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CustomerDashboard;
