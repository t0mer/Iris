import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { Chats } from '../../src/pages/Chats'
import { Messages } from '../../src/pages/Messages'
import { setLanguage } from '../../src/lib/i18n'
afterEach(() => setLanguage('system'))
test.each([
  { Component: Chats, path: '/chats', api: '/api/chats', response: [] },
  {
    Component: Messages,
    path: '/messages',
    api: '/api/messages',
    response: { items: [], total: 0, page: 1, page_size: 50 },
  },
])(
  '$path translates type labels and submits canonical filter values',
  async ({ Component, path, api, response }) => {
    setLanguage('he')
    const calls = renderWithApp(<Component />, { [api]: response, '/api/auth/phones': [] }, path)
    const select = await screen.findByLabelText('סוג')
    expect(screen.getByRole('option', { name: 'מסמך' })).toHaveValue('document')
    expect(screen.getByRole('option', { name: 'מדבקה' })).toHaveValue('sticker')
    expect(screen.queryByRole('option', { name: 'image' })).not.toBeInTheDocument()
    await userEvent.selectOptions(select, 'document')
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.url.startsWith(api) &&
            new URL(call.url, 'http://iris').searchParams.get('type') === 'document',
        ),
      ).toBe(true),
    )
  },
)
