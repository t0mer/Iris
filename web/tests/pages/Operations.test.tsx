import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { ScheduleSettings } from '../../src/pages/ScheduleSettings'
import { AuditSettings } from '../../src/pages/AuditSettings'
import { AlertDeliveryHealth } from '../../src/components/AlertDeliveryHealth'

test('schedule history shows errors and stack traces with a bounded history explanation', async () => {
  renderWithApp(<ScheduleSettings />, {
    '/api/schedules': {
      timezone: 'Asia/Jerusalem',
      workers_enabled: true,
      history_policy: '10 runs; 3 recent failures; 4 days',
      items: [
        {
          key: 'daily_summary',
          name: 'Daily summary',
          description: 'Assigned children only',
          enabled: true,
          interval: null,
          time: '20:00',
          channel: 'telegram',
          recipients: [
            {
              target: 'email:parent@example.com',
              name: 'Parent',
              eligible: true,
              children: ['Noa'],
            },
          ],
          runs: [
            {
              id: 1,
              status: 'failed',
              started_at: '2026-10-09T09:00:00Z',
              error: 'Provider rejected request',
              traceback: 'RuntimeError: provider failure',
            },
          ],
        },
      ],
    },
  })
  expect(await screen.findByText('Parent: Eligible · Noa')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Run history' }))
  await userEvent.click(await screen.findByText(/#1 · failed/))
  expect(await screen.findByText('RuntimeError: provider failure')).toBeInTheDocument()
})

test('audit displays the user and before/after values', async () => {
  renderWithApp(<AuditSettings />, {
    '/api/audit': {
      total: 1,
      items: [
        {
          id: 1,
          username: 'Parent',
          method: 'PUT',
          path: '/api/settings',
          status_code: 200,
          created_at: '2026-10-09T09:00:00Z',
          changes: [
            {
              entity: 'Setting',
              id: 'alerts.channel',
              field: 'value',
              before: 'smtp',
              after: 'telegram',
            },
          ],
        },
      ],
    },
  })
  await userEvent.click(await screen.findByText('Parent'))
  expect(await screen.findByText('"smtp"')).toBeInTheDocument()
  expect(await screen.findByText('"telegram"')).toBeInTheDocument()
})

test('one eligible recipient does not hide invalid recipients', async () => {
  renderWithApp(<AlertDeliveryHealth channel="openwa" />, {
    '/api/settings/alert-readiness': {
      ready: true,
      eligible_count: 1,
      invalid_count: 1,
      recipients: [
        { target: 'a', name: 'Approved parent', eligible: true },
        {
          target: 'b',
          name: 'Unapproved parent',
          eligible: false,
          reason: 'WhatsApp number is not approved.',
        },
      ],
    },
  })
  expect(await screen.findByText('WhatsApp number is not approved.')).toBeInTheDocument()
  expect(
    screen.getByText('1 eligible recipient(s) across their selected channels.'),
  ).toBeInTheDocument()
})

test('device schedule saves configurable retry count and notification wait', async () => {
  const calls = renderWithApp(<ScheduleSettings />, {
    '/api/settings': { 'schedules.config': {} },
    '/api/schedules': {
      timezone: 'Asia/Jerusalem',
      workers_enabled: true,
      history_policy: '10 runs',
      items: [
        {
          key: 'connections',
          name: 'Device verification',
          description: 'Verify',
          enabled: true,
          interval: 60,
          retry_count: 1,
          retry_wait_minutes: 10,
          notify_wait_minutes: 10,
          runs: [],
          recipients: [],
        },
      ],
    },
  })
  const count = await screen.findByLabelText('Automatic refresh attempts')
  await userEvent.clear(count)
  await userEvent.type(count, '2')
  await userEvent.click(screen.getByRole('button', { name: 'Save automatic refresh attempts' }))
  expect(calls.find((c) => c.method === 'PUT')?.body).toMatchObject({
    settings: { 'schedules.config': { connections: { retry_count: 2 } } },
  })
  const wait = screen.getByLabelText('Wait before notifying parents (minutes)')
  expect(wait).toHaveValue(10)
})
