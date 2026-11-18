import { useCallback, useEffect, useRef } from "react"
import { captureSession } from "../api/client.ts"

export interface RequestLifetime {
  isCurrent: () => boolean
  signal: AbortSignal
}

export function useRequestLifetime() {
  const generation = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const invalidateRequests = useCallback(() => {
    generation.current += 1
    controller.current?.abort()
    controller.current = null
  }, [])
  const captureRequest = useCallback(() => {
    controller.current?.abort()
    const requestController = new AbortController()
    controller.current = requestController
    const startedGeneration = generation.current
    const isCurrentSession = captureSession()
    return {
      signal: requestController.signal,
      isCurrent: () => startedGeneration === generation.current && isCurrentSession() && !requestController.signal.aborted,
    }
  }, [])
  useEffect(() => invalidateRequests, [invalidateRequests])
  return { captureRequest, invalidateRequests }
}
