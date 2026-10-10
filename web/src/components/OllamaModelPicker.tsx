import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { Button } from './ui/button'
import { Field, Input, Select } from './ui/field'

export function OllamaModelPicker({
  endpoint,
  value,
  onChange,
}: {
  endpoint: string
  value: string
  onChange: (value: string) => void
}) {
  const [host, setHost] = useState(endpoint)
  useEffect(() => {
    const timer = setTimeout(() => setHost(endpoint), 600)
    return () => clearTimeout(timer)
  }, [endpoint])
  const models = useQuery({
    queryKey: ['ollama-models', host],
    queryFn: async () => {
      const result = await api<{ models: { name: string; vision: boolean | null }[] }>(
        '/api/settings/ollama/models',
        { method: 'POST', body: JSON.stringify({ base_url: host || undefined }) },
      )
      if (!Array.isArray(result.models))
        throw new Error('Could not detect installed Ollama models.')
      return result.models
    },
    retry: false,
    staleTime: 60_000,
  })
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <Field label="Installed Ollama models">
        <Select
          value={models.data?.some((m) => m.name === value) ? value : ''}
          onChange={(e) => {
            if (e.target.value) onChange(e.target.value)
          }}
          disabled={models.isFetching || !models.data?.length}
        >
          <option value="">
            {models.isFetching ? 'Detecting models…' : 'Choose an installed model…'}
          </option>
          {models.data?.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name} ·{' '}
              {m.vision === true
                ? 'Text + images'
                : m.vision === false
                  ? 'No vision'
                  : 'Vision unknown'}
            </option>
          ))}
        </Select>
      </Field>
      <Button
        className="self-start"
        disabled={models.isFetching || host !== endpoint}
        onClick={() => void models.refetch()}
      >
        Refresh models
      </Button>
      {models.isError && (
        <p role="alert" className="text-sm text-danger">
          {models.error.message} You can enter a model below.
        </p>
      )}
      {models.data?.length === 0 && (
        <p className="text-sm">No models installed on this Ollama server.</p>
      )}
      <Field
        label="Ollama model"
        hint="Detected models come from the entered endpoint. Your current choice stays selected; changes take effect when saved. You can also enter a custom model name."
      >
        <Input aria-label="Ollama model" value={value} onChange={(e) => onChange(e.target.value)} />
      </Field>
    </div>
  )
}
