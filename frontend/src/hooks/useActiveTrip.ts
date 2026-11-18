import { useRequestLifetime } from "./useRequestLifetime"
import { useCallback, useEffect, useState } from "react"
import {
  createTrip, getTripSnapshot, listTrips, searchTripFlights,
  extractErrorMessage,
} from "../api/client"
import type {
  FlightOfferOut, FlightSearchOut, TripRequestCreate, TripRequestOut,
} from "../api/types"

const ACTIVE_TRIP_ID_STORAGE_KEY = "travel-agent.activeTripId"

export function useActiveTrip(isAuthenticated: boolean | null) {
  const [trip, setTrip] = useState<TripRequestOut | null>(null)
  const [isRestoringTrip, setIsRestoringTrip] = useState(false)
  const [restoreTripError, setRestoreTripError] = useState<string | null>(null)
  const [isCreatingTrip, setIsCreatingTrip] = useState(false)
  const [createTripError, setCreateTripError] = useState<string | null>(null)

  const [trips, setTrips] = useState<TripRequestOut[]>([])

  const [flightSearchResult, setFlightSearchResult] = useState<FlightSearchOut | null>(null)
  const [isSearchingFlights, setIsSearchingFlights] = useState(false)
  const [flightSearchError, setFlightSearchError] = useState<string | null>(null)
  const [selectedOffer, setSelectedOffer] = useState<FlightOfferOut | null>(null)

  const isRunActive = isSearchingFlights

  const { captureRequest, invalidateRequests } = useRequestLifetime()
  const { captureRequest: captureFlightRequest, invalidateRequests: invalidateFlightRequests } = useRequestLifetime()
  const { captureRequest: captureTripListRequest } = useRequestLifetime()
  const beginSelection = useCallback(() => {
    invalidateRequests()
    invalidateFlightRequests()
    setIsCreatingTrip(false)
    setIsRestoringTrip(false)
    setRestoreTripError(null)
    setIsSearchingFlights(false)
    return captureRequest()
  }, [captureRequest, invalidateRequests, invalidateFlightRequests])

  const restoreTrip = useCallback((tripId: number) => {
    const request = beginSelection()
    setIsRestoringTrip(true)
    setRestoreTripError(null)
    return getTripSnapshot(tripId, request.signal).then((snapshot) => {
      if (!request.isCurrent()) return
      setTrip(snapshot.trip)
      setFlightSearchResult(snapshot.flight_search)
      localStorage.setItem(ACTIVE_TRIP_ID_STORAGE_KEY, String(tripId))
    }).catch((error) => {
      if (!request.isCurrent()) return
      localStorage.removeItem(ACTIVE_TRIP_ID_STORAGE_KEY)
      setRestoreTripError(extractErrorMessage(error))
    }).finally(() => {
      if (request.isCurrent()) setIsRestoringTrip(false)
    })
  }, [beginSelection])

  // Restore the active trip after a hard refresh so the execution history survives. React state
  // alone would lose the trip id and leave the ExecutionPanel with nothing to re-fetch.
  useEffect(() => {
    if (!isAuthenticated) return
    const storedTripId = localStorage.getItem(ACTIVE_TRIP_ID_STORAGE_KEY)
    if (!storedTripId) return
    restoreTrip(Number(storedTripId))
  }, [isAuthenticated, restoreTrip])

  useEffect(() => {
    if (!isAuthenticated) return
    const request = captureTripListRequest()
    listTrips(request.signal)
      .then((result) => {
        if (!request.isCurrent()) return
        setTrips((previousTrips) => {
          // A local create wins over a stale row from a list fetch still in flight.
          const merged = new Map(result.map((listedTrip) => [listedTrip.id, listedTrip]))
          previousTrips.forEach((previousTrip) => merged.set(previousTrip.id, previousTrip))
          return Array.from(merged.values()).sort((left, right) => right.id - left.id)
        })
      })
      .catch(() => {})
  }, [isAuthenticated, captureTripListRequest])

  const handleCreateTrip = async (tripRequestCreate: TripRequestCreate) => {
    const request = beginSelection()
    setIsCreatingTrip(true)
    setCreateTripError(null)
    try {
      const createdTrip = await createTrip(tripRequestCreate, request.signal)
      if (!request.isCurrent()) return
      setTrip(createdTrip)
      localStorage.setItem(ACTIVE_TRIP_ID_STORAGE_KEY, String(createdTrip.id))
      setTrips((previousTrips) => [createdTrip, ...previousTrips])
    } catch (error) {
      if (!request.isCurrent()) return
      setCreateTripError(extractErrorMessage(error))
    } finally {
      if (request.isCurrent()) setIsCreatingTrip(false)
    }
  }

  const handleSearchFlights = async () => {
    if (!trip || isRestoringTrip) return
    const request = captureFlightRequest()
    setIsSearchingFlights(true)
    setFlightSearchError(null)
    setSelectedOffer(null)
    try {
      const result = await searchTripFlights(trip.id, request.signal)
      if (!request.isCurrent()) return
      setFlightSearchResult(result)
    } catch (error) {
      if (!request.isCurrent()) return
      setFlightSearchError(extractErrorMessage(error))
    } finally {
      if (request.isCurrent()) setIsSearchingFlights(false)
    }
  }

  const handleStartNewSearch = () => {
    beginSelection()
    localStorage.removeItem(ACTIVE_TRIP_ID_STORAGE_KEY)
    setTrip(null)
    clearFlightAndBookingState()
  }

  const handleSearchAgain = () => {
    setSelectedOffer(null)
  }

  const handleSelectTrip = (tripId: number) => {
    if (trip?.id === tripId) return
    clearFlightAndBookingState()
    restoreTrip(tripId)
  }

  const clearFlightAndBookingState = () => {
    setFlightSearchResult(null)
    setSelectedOffer(null)
    setFlightSearchError(null)
  }

  return {
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
    isRunActive,
    handleCreateTrip,
    handleSearchFlights,
    handleStartNewSearch,
    handleSearchAgain,
    handleSelectTrip,
  }
}
