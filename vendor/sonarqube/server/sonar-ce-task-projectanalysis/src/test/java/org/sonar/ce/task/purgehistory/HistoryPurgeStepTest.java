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

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import org.jetbrains.annotations.NotNull;
import org.junit.Before;
import org.junit.Test;
import org.sonar.ce.task.projectanalysis.history.HistoryPurgeStep;
import org.sonar.ce.task.step.ComputationStep;
import org.sonar.db.DbClient;
import org.sonar.db.property.PropertiesDao;
import org.sonar.db.property.PropertyDto;
import org.sonarsource.history.server.service.HistoryPurgeService;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.sonar.core.config.PurgeConstants.DAYS_BEFORE_DELETING_HISTORY;

public class HistoryPurgeStepTest {

  private final DbClient dbClient = mock();
  private final PropertiesDao propertiesDao = mock();
  private final HistoryPurgeService historyPurgeService = mock();

  private final ComputationStep.Context context = mock();
  private final Clock clock = Clock.fixed(Instant.parse("2026-07-22T10:00:00Z"), ZoneOffset.UTC);
  private final HistoryPurgeStep underTest = new HistoryPurgeStep(historyPurgeService, dbClient, clock);

  @Before
  public void setup() {
    when(dbClient.propertiesDao()).thenReturn(propertiesDao);
  }

  @Test
  public void executeShouldGetPropertyAndCallService() {
    PropertyDto propertyDto = thresholdPropertyWithValue("100");
    when(propertiesDao.selectGlobalProperty(any(), eq(DAYS_BEFORE_DELETING_HISTORY)))
      .thenReturn(propertyDto);

    underTest.execute(context);

    var expectedThresholdDate = today().minusDays(100);
    verify(historyPurgeService).purgeHistoryBefore(expectedThresholdDate);
  }

  @Test
  public void executeShouldFallBackOnDefaultThresholdWhenUnableToParseProperty() {
    PropertyDto propertyDto = thresholdPropertyWithValue("asdf");
    when(propertiesDao.selectGlobalProperty(any(), eq(DAYS_BEFORE_DELETING_HISTORY)))
      .thenReturn(propertyDto);

    underTest.execute(context);

    var expectedThresholdDate = today().minusDays(365);
    verify(historyPurgeService).purgeHistoryBefore(expectedThresholdDate);
  }

  @Test
  public void executeShouldFallBackOnDefaultThresholdWhenPropertyMissing() {
    when(propertiesDao.selectGlobalProperty(any(), eq(DAYS_BEFORE_DELETING_HISTORY)))
      .thenReturn(null);

    underTest.execute(context);

    var expectedThresholdDate = today().minusDays(365);
    verify(historyPurgeService).purgeHistoryBefore(expectedThresholdDate);
  }

  private static @NotNull PropertyDto thresholdPropertyWithValue(String value) {
    PropertyDto propertyDto = new PropertyDto();
    propertyDto.setKey(DAYS_BEFORE_DELETING_HISTORY);
    propertyDto.setValue(value);
    return propertyDto;
  }

  private LocalDate today() {
    return LocalDate.from(clock.instant().atZone(ZoneOffset.UTC));
  }

  @Test
  public void getDescription() {
    assertThat(underTest.getDescription()).isEqualTo("Purge History");
  }
}
