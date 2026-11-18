import { useCallback, useEffect, useState } from "react"
import {
  AUTHENTICATION_REQUIRED_EVENT,
  SESSION_CHANGED_STORAGE_KEY,
  getBrowserSession,
  getAuthConfig,
  login,
  verifyMfa,
  extractErrorMessage,
} from "./api/client"
import { ApprovalHistoryPanel } from "./components/ApprovalHistoryPanel"
import { BookingModule } from "./components/BookingModule"
import { ConnectorsPanel } from "./components/ConnectorsPanel"
import { CompliancePanel } from "./components/CompliancePanel"
import { ExecutionPanel } from "./components/ExecutionPanel"
import { FlightSearch } from "./components/FlightSearch"
import { ItineraryPanel } from "./components/ItineraryPanel"
import { LiveActivity } from "./components/LiveActivity"
import { Questionnaire } from "./components/Questionnaire"
import { useActiveTrip } from "./hooks/useActiveTrip"
import { YourTripsPanel } from "./components/YourTripsPanel"

export function LoginPanel({ onAuthenticated }: { onAuthenticated: () => void | Promise<void> }) {
  const [email, setEmail] = useState("traveler@tenant-a.test")
  const [password, setPassword] = useState("")
  const [deviceId, setDeviceId] = useState("device-a-traveler")
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [code, setCode] = useState("")
  const [error, setError] = useState<string | null>(null)

  const submitLogin = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    try {
      const result = await login(email, password, deviceId)
      if (result.mfa_required) setSessionId(result.session_id)
      else await onAuthenticated()
    } catch (error) {
      setError(extractErrorMessage(error))
    }
  }

  const submitMfa = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!sessionId) return
    setError(null)
    try {
      await verifyMfa(sessionId, code)
      await onAuthenticated()
    } catch (error) {
      setError(extractErrorMessage(error))
    }
  }

  // Without this, an expired or revoked MFA session traps the form resubmitting a dead session.
  const restartSignIn = () => {
    setSessionId(null)
    setCode("")
    setError(null)
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
      <form onSubmit={sessionId ? submitMfa : submitLogin} className="w-full max-w-sm space-y-4 rounded-xl bg-white p-6 shadow">
        <h1 className="text-2xl font-bold">Travel Agent sign in</h1>
        {!sessionId ? (
          <>
            <input aria-label="Email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Email" className="w-full rounded border p-2" />
            <input aria-label="Password" required type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Password" className="w-full rounded border p-2" />
            <input aria-label="Device" required value={deviceId} onChange={(event) => setDeviceId(event.target.value)} placeholder="Device ID" className="w-full rounded border p-2" />
            <button type="submit" className="w-full rounded bg-indigo-600 p-2 text-white">Continue to MFA</button>
          </>
        ) : (
          <>
            <label className="block text-sm">Enter your authenticator code
              <input aria-label="MFA code" required inputMode="numeric" value={code} onChange={(event) => setCode(event.target.value)} className="mt-1 w-full rounded border p-2" />
            </label>
            <button type="submit" className="w-full rounded bg-indigo-600 p-2 text-white">Verify and sign in</button>
            <button type="button" onClick={restartSignIn} className="w-full rounded border border-slate-300 p-2 text-sm text-slate-600">Start over</button>
          </>
        )}
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      </form>
    </main>
  )
}

type TabKey = "trip" | "trips" | "execution" | "approvals" | "connectors" | "compliance"

const TABS: { key: TabKey; label: string; roles: string[]; privileged?: boolean; icon: string }[] = [
  { key: "trip", label: "Plan a trip", roles: ["traveler", "trip-planner", "admin"], icon: "M12 5v14m-7-7h14" },
  { key: "trips", label: "Your trips", roles: ["traveler", "trip-planner", "admin"], icon: "M4 7h16v13H4zM9 7V4h6v3" },
  { key: "execution", label: "Agent execution history", roles: ["trip-planner", "admin"], icon: "M4 12h4l3-8 3 16 3-8h3" },
  { key: "approvals", label: "Approval history", roles: ["trip-planner", "admin"], icon: "M5 4h14v16H5zM8 12l3 3 5-6" },
  { key: "connectors", label: "Connectors", roles: ["security-operator", "admin"], privileged: true, icon: "M9 3v5m6-5v5M7 8h10v4a5 5 0 0 1-10 0zM12 17v4" },
  { key: "compliance", label: "Security monitoring", roles: ["security-operator", "platform-operator", "admin"], privileged: true, icon: "M12 3l8 3v6c0 4-8 9-8 9s-8-5-8-9V6z" },
]

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null)
  const [activeTab, setActiveTab] = useState<TabKey>("trip")
  const [role, setRole] = useState("traveler")
  const [mfaVerified, setMfaVerified] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [isBookingActionPending, setIsBookingActionPending] = useState(false)
  const tabs = TABS.filter((tab) => tab.roles.includes(role) && (!tab.privileged || mfaVerified))
  const currentTab = tabs.find((tab) => tab.key === activeTab) ?? tabs[0]
  const canPlanTrips = ["traveler", "trip-planner", "admin"].includes(role)
  const loadSession = useCallback(async () => {
    const session = await getBrowserSession()
    setRole(session.role)
    setMfaVerified(session.mfa_verified)
    setIsAuthenticated(true)
  }, [])

  const {
    trip,
    isRestoringTrip,
    restoreTripError,
    isCreatingTrip,
    createTripError,
    trips,
    flightSearchResult,
    isSearchingFlights,
    flightSearchError,
    selectedOffer,
    setSelectedOffer,
    planResult,
    isPlanning,
    planError,
    isRunActive,
    handleCreateTrip,
    handleSearchFlights,
    handleStartNewSearch,
    handleRequestPlan,
    handleAnswerClarification,
    handleSearchAgain,
    handleSelectTrip,
  } = useActiveTrip(isAuthenticated && canPlanTrips)

  useEffect(() => {
    const requireAuthentication = () => window.location.reload()
    const sessionChanged = (event: StorageEvent) => {
      if (event.storageArea === localStorage && event.key === SESSION_CHANGED_STORAGE_KEY && event.newValue)
        window.location.reload()
    }
    window.addEventListener(AUTHENTICATION_REQUIRED_EVENT, requireAuthentication)
    window.addEventListener("storage", sessionChanged)
    return () => {
      window.removeEventListener(AUTHENTICATION_REQUIRED_EVENT, requireAuthentication)
      window.removeEventListener("storage", sessionChanged)
    }
  }, [])

  useEffect(() => {
    getAuthConfig()
      .then(async ({ enforced }) => {
        if (enforced) await loadSession()
        else setIsAuthenticated(true)
      })
      .catch(() => setIsAuthenticated(false))
  }, [loadSession])

  if (isAuthenticated === null) return null
  if (!isAuthenticated) return <LoginPanel onAuthenticated={loadSession} />

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900 md:flex-row">
      <aside className={`m-3 flex shrink-0 flex-col rounded-2xl border border-slate-200 bg-white shadow-sm md:sticky md:top-3 md:h-[calc(100vh-1.5rem)] ${sidebarCollapsed ? "md:w-20" : "md:w-72"}`}>
        <div className={`flex items-center gap-2 border-b border-slate-200 py-5 ${sidebarCollapsed ? "justify-center px-2" : "justify-between px-5"}`}>
          <h1 className={sidebarCollapsed ? "sr-only" : "text-xl font-bold tracking-tight text-slate-900"}>
            Travel Agent
          </h1>
          <button type="button" aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!sidebarCollapsed} aria-controls="primary-navigation"
            onClick={() => setSidebarCollapsed((previous) => !previous)}
            className="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-indigo-600">
            <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M4 4h16v16H4zM9 4v16" /></svg>
          </button>
        </div>

        <nav id="primary-navigation" className="space-y-3 p-3" aria-label="Primary">
          {tabs.map((tab) => {
            const isActive = currentTab?.key === tab.key
            return (
              <button
                key={tab.key}
                type="button"
                aria-label={tab.label}
                title={sidebarCollapsed ? tab.label : undefined}
                onClick={() => setActiveTab(tab.key)}
                aria-current={isActive ? "page" : undefined}
                className={`flex min-h-12 w-full items-center gap-3 rounded-xl border px-3 py-3 text-left text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-indigo-600 ${sidebarCollapsed ? "justify-center" : ""} ${
                  isActive
                    ? "border-indigo-300 bg-indigo-50 text-indigo-800 shadow-sm"
                    : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
                }`}
              >
                <svg className="shrink-0" aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d={tab.icon} /></svg>
                <span className={sidebarCollapsed ? "sr-only" : "flex-1"}>{tab.label}</span>
                {tab.key === "execution" && isRunActive && (
                  <span className="relative flex h-2 w-2" aria-label="run in progress">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-indigo-500" />
                  </span>
                )}
              </button>
            )
          })}
        </nav>

        <div className="flex-1" />
      </aside>

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <main aria-label={currentTab?.label ?? "Workspace"} className="mx-auto w-full min-w-0 max-w-4xl flex-1 space-y-6 px-4 py-6 sm:px-6">
          {currentTab?.key === "trip" && (
            <>
              {restoreTripError && <p role="alert">{restoreTripError}</p>}
              {isRestoringTrip && <p role="status">Loading trip…</p>}
              {!trip && !isRestoringTrip && (
                <Questionnaire
                  onSubmit={handleCreateTrip}
                  isSubmitting={isCreatingTrip}
                  errorMessage={createTripError}
                />
              )}

              {trip && !isRestoringTrip && (
                <>
                  <FlightSearch
                    trip={trip}
                    searchResult={flightSearchResult}
                    isLoading={isSearchingFlights}
                    errorMessage={flightSearchError}
                    selectedOfferId={selectedOffer?.id ?? null}
                    onSearchFlights={handleSearchFlights}
                    onSearchNewFlight={handleStartNewSearch}
                    onSelectOffer={setSelectedOffer}
                    selectionDisabled={isBookingActionPending}
                  />

                  {(["traveler", "admin"].includes(role)) && (
                    <BookingModule
                      key={selectedOffer ? selectedOffer.id : "none"}
                      trip={trip}
                      selectedOffer={selectedOffer}
                      onSearchAgain={handleSearchAgain}
                      onPendingChange={setIsBookingActionPending}
                    />
                  )}

                  <ItineraryPanel
                    trip={trip}
                    planResult={planResult}
                    isLoading={isPlanning}
                    errorMessage={planError}
                    onRequestPlan={handleRequestPlan}
                    onAnswerClarification={handleAnswerClarification}
                  />

                  <LiveActivity tripId={trip.id} isRunActive={isRunActive} />
                </>
              )}
            </>
          )}

          {currentTab?.key === "trips" && (
            <YourTripsPanel
              trips={trips}
              selectedTripId={trip?.id ?? null}
              onSelectTrip={(tripId) => { handleSelectTrip(tripId); setActiveTab("trip") }}
            />
          )}

          {currentTab?.key === "execution" && <ExecutionPanel trips={trips} isRunActive={isRunActive} />}

          {currentTab?.key === "approvals" && (
            <ApprovalHistoryPanel trips={trips} isRunActive={isRunActive} />
          )}

          {currentTab?.key === "connectors" && <ConnectorsPanel />}
          {currentTab?.key === "compliance" && <CompliancePanel />}
        </main>

        <footer className="mt-10 border-t border-slate-200 py-6 text-center text-xs text-slate-400">
          <p>flights via Google Flights (SearchApi.io) · activity research via Tavily</p>
        </footer>
      </div>
    </div>
  )
}

export default App
