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
package org.sonar.server.platform.db.migration.version.v202605;

import java.sql.SQLException;
import org.sonar.db.Database;
import org.sonar.server.platform.db.migration.sql.CreateIndexBuilder;
import org.sonar.server.platform.db.migration.sql.CreateTableBuilder;
import org.sonar.server.platform.db.migration.step.CreateTableChange;

import static org.sonar.server.platform.db.migration.def.IntegerColumnDef.newIntegerColumnDefBuilder;
import static org.sonar.server.platform.db.migration.def.VarcharColumnDef.newVarcharColumnDefBuilder;
import static org.sonar.server.platform.db.migration.sql.CreateTableBuilder.ColumnFlag.AUTO_INCREMENT;

public class CreateScaIssueDimensionsTable extends CreateTableChange {

  static final String TABLE_NAME = "sca_issue_dimensions";
  static final String COLUMN_ID = "id";
  static final String COLUMN_DIMENSION_HASH = "dimension_hash";
  static final String COLUMN_SEVERITY = "severity";
  static final String COLUMN_STATUS = "status";
  static final String INDEX_DIMENSION_HASH = "sca_issue_dimensions_hash";

  static final int DIMENSION_HASH_SIZE = 32;
  static final int SEVERITY_SIZE = 32;
  static final int STATUS_SIZE = 32;

  protected CreateScaIssueDimensionsTable(Database db) {
    super(db, TABLE_NAME);
  }

  @Override
  public void execute(Context context, String tableName) throws SQLException {
    var dialect = getDialect();

    context.execute(new CreateTableBuilder(dialect, tableName)
      .addPkColumn(newIntegerColumnDefBuilder().setColumnName(COLUMN_ID).setIsNullable(false).build(), AUTO_INCREMENT)
      .addColumn(newVarcharColumnDefBuilder().setColumnName(COLUMN_DIMENSION_HASH).setIsNullable(false).setLimit(DIMENSION_HASH_SIZE).build())
      .addColumn(newVarcharColumnDefBuilder().setColumnName(COLUMN_SEVERITY).setIsNullable(false).setLimit(SEVERITY_SIZE).build())
      .addColumn(newVarcharColumnDefBuilder().setColumnName(COLUMN_STATUS).setIsNullable(true).setLimit(STATUS_SIZE).build())
      .build());

    context.execute(new CreateIndexBuilder(dialect)
      .setTable(tableName)
      .setName(INDEX_DIMENSION_HASH)
      .setUnique(true)
      .addColumn(COLUMN_DIMENSION_HASH, false)
      .build());
  }
}
