import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Tabs, TabsList, TabsTrigger } from './tabs'

test('tabs use RTL keyboard navigation', async () => {
  render(
    <Tabs defaultValue="first">
      <TabsList>
        <TabsTrigger value="first">ראשון</TabsTrigger>
        <TabsTrigger value="second">שני</TabsTrigger>
      </TabsList>
    </Tabs>,
  )
  const first = screen.getByRole('tab', { name: 'ראשון' })
  first.focus()
  await userEvent.keyboard('{ArrowLeft}')
  expect(screen.getByRole('tab', { name: 'שני' })).toHaveFocus()
})
