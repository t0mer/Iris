import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OllamaModelPicker } from '../../src/components/OllamaModelPicker'
import { renderWithApp } from '../test-utils'

test('detects installed vision models without replacing the current choice', async () => {
  const onChange = vi.fn()
  renderWithApp(<OllamaModelPicker endpoint="http://ollama" value="custom" onChange={onChange} />, {
    '/api/settings/ollama/models': {
      models: [
        { name: 'vision', vision: true },
        { name: 'text', vision: false },
      ],
    },
  })
  await screen.findByRole('option', { name: 'vision · Text + images' })
  expect(onChange).not.toHaveBeenCalled()
  expect(screen.getByLabelText('Ollama model')).toHaveValue('custom')
  await userEvent.selectOptions(screen.getByLabelText('Installed Ollama models'), 'vision')
  expect(onChange).toHaveBeenCalledWith('vision')
})
