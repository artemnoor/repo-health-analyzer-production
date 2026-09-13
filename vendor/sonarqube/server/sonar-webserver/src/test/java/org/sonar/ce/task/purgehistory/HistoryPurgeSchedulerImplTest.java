/*
 * SonarQube
 * Copyright (C) SonarSource Sàrl
 * mailto:info AT sonarsource DOT com
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 3 of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with this program; if not, write to the Free Software Foundation,
 * Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
 */
package org.sonar.ce.task.purgehistory;

import java.util.concurrent.TimeUnit;
import org.junit.Before;
import org.junit.Test;
import org.mockito.ArgumentCaptor;
import org.sonar.ce.queue.CeQueue;
import org.sonar.ce.queue.CeTaskSubmit;
import org.sonar.core.util.SequenceUuidFactory;
import org.sonar.core.util.UuidFactory;
import org.sonar.server.util.GlobalLockManager;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class HistoryPurgeSchedulerImplTest {

  private final GlobalLockManager lockManager = mock(GlobalLockManager.class);
  private final HistoryPurgeExecutorService executorService = mock(HistoryPurgeExecutorService.class);
  private final CeQueue ceQueue = mock(CeQueue.class);
  private final UuidFactory uuidFactory = new SequenceUuidFactory();
  private final HistoryPurgeSchedulerImpl underTest = new HistoryPurgeSchedulerImpl(executorService, ceQueue, lockManager);

  @Before
  public void prepare() {
    when(lockManager.tryLock(any(), anyInt())).thenReturn(true);
    when(ceQueue.prepareSubmit()).thenReturn(new CeTaskSubmit.Builder(uuidFactory.create()));
  }

  @Test
  public void startSchedulingSchedulesTaskImmediatelyAndEvery24Hours() {
    underTest.startScheduling();

    verify(executorService).scheduleAtFixedRate(any(Runnable.class), eq(0L), eq(24L), eq(TimeUnit.HOURS));
  }

  @Test
  public void doNothingIfLocked() {
    when(lockManager.tryLock(any(), anyInt())).thenReturn(false);

    runScheduledTask();

    verify(ceQueue, never()).submit(any());
  }

  @Test
  public void doNothingIfExceptionIsThrown() {
    when(lockManager.tryLock(any(), anyInt())).thenThrow(new IllegalArgumentException("Oops"));

    runScheduledTask();

    verify(ceQueue, never()).submit(any());
  }

  @Test
  public void schedulePurgeTaskWhenNotLocked() {
    runScheduledTask();

    verify(ceQueue).submit(any());
  }

  private void runScheduledTask() {
    underTest.startScheduling();
    ArgumentCaptor<Runnable> task = ArgumentCaptor.forClass(Runnable.class);
    verify(executorService).scheduleAtFixedRate(task.capture(), anyLong(), anyLong(), any(TimeUnit.class));
    task.getValue().run();
  }
}
