`timescale 1ns/1ps

// Ensure Assignments > Settings > EDA Tool Settings > Simulation > Tool Name is "ModelSim-Altera"
// Navigate to ModelSim Altera:
//     Tool > Run Simulation Tool > RTL Simulation
// In the ModelSim Altera transcript, run:
/*
do Thesis_Project_Bit_Manipulation_run_dispest_tb.do
*/

module disparity_estimator_tb;

	// ------------------------------------------------------------------------
	// Clock
	// ------------------------------------------------------------------------
	localparam int TCLK_NS = 20;

	logic clock_50 = 1'b0;
	always #(TCLK_NS/2) clock_50 = ~clock_50;

	// ------------------------------------------------------------------------
	// Parameters
	// ------------------------------------------------------------------------
	parameter int unsigned IMAGE_DIM         = 128;
	parameter int unsigned IMAGE_DIM_BS      = 7;
	parameter int unsigned CAPTURES_PER_AXIS = 9;
	parameter int unsigned DERIVATIVE_COUNT  = 7;

	// ------------------------------------------------------------------------
	// Paths
	// ------------------------------------------------------------------------
	localparam string IN_DIR  = "/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/tb/disp_est/input_data";
	localparam string OUT_DIR = "/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/tb/disp_est/output_data";

	// ------------------------------------------------------------------------
	// Input filenames : EPI stream
	// ------------------------------------------------------------------------
	localparam string IN_EPI_VALID_MIF       = {IN_DIR, "/SIM_EPI_VALID_IN.mif"};
	localparam string IN_EPI_COLUMN_IDX_MIF  = {IN_DIR, "/SIM_EPI_COLUMN_IDX_IN.mif"};
	localparam string IN_EPI_IDX_MIF         = {IN_DIR, "/SIM_EPI_IDX_IN.mif"};
	localparam string IN_EPI_ORIENTATION_MIF = {IN_DIR, "/SIM_ORIENTATION_IN.mif"};

	// ------------------------------------------------------------------------
	// Input filenames : angular derivative stream
	// ------------------------------------------------------------------------
	localparam string IN_ANG_DERIV_VALID_MIF       = {IN_DIR, "/SIM_DERIVATIVE_VALID_OUT.mif"};
	localparam string IN_ANG_DERIV_COLUMN_IDX_MIF  = {IN_DIR, "/SIM_DERIVATIVE_COLUMN_IDX_OUT.mif"};
	localparam string IN_ANG_DERIV_ROW_IDX_MIF     = {IN_DIR, "/SIM_DERIVATIVE_ROW_IDX_OUT.mif"};
	localparam string IN_ANG_DERIV_ORIENTATION_MIF = {IN_DIR, "/SIM_DERIVATIVE_ORIENTATION_OUT.mif"};

	// ------------------------------------------------------------------------
	// Output filenames : disparity
	// ------------------------------------------------------------------------
	localparam string OUT_DISP_VALID_MIF       = "SIM_DISP_VALID_OUT.mif";
	localparam string OUT_DISP_PIXEL_MIF       = "SIM_DISP_PIXEL_OUT.mif";
	localparam string OUT_DISP_ROW_IDX_MIF     = "SIM_DISP_ROW_IDX_OUT.mif";
	localparam string OUT_DISP_COLUMN_IDX_MIF  = "SIM_DISP_COLUMN_IDX_OUT.mif";
	localparam string OUT_DISP_ORIENTATION_MIF = "SIM_DISP_ORIENTATION_OUT.mif";

	// ------------------------------------------------------------------------
	// Depth / sizes
	// ------------------------------------------------------------------------
	localparam int VERTICAL_POST_FRAME_CYCLES = (IMAGE_DIM * IMAGE_DIM);
	localparam int EXTRA_TAIL    = VERTICAL_POST_FRAME_CYCLES;
	localparam int MAX_DEPTH     = 381500 + EXTRA_TAIL;
	localparam int WARMUP_CYCLES = 8;
	localparam int OUT_MAX_DEPTH = 4 + WARMUP_CYCLES + MAX_DEPTH + EXTRA_TAIL + 64;

	// confidence_computer_tb captured derivative outputs for:
	//   4 settle cycles + WARMUP_CYCLES + full input stream + EXTRA_TAIL + 1 (In top level output is only one cycle after not 2)
	// So to align derivative outputs with the raw EPI input stream, skip:
	localparam int ANG_DERIV_TRIM_OFFSET = 4 + WARMUP_CYCLES + 1; // = 13

	int DEPTH_EPI       = 0;
	int DEPTH_ANG_DERIV = 0;
	int DEPTH           = 0;

	// ------------------------------------------------------------------------
	// Input memories : EPI stream
	// ------------------------------------------------------------------------
	logic                    epi_valid_mem       [0:MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] epi_column_idx_mem  [0:MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] epi_idx_mem         [0:MAX_DEPTH-1];
	logic                    epi_orientation_mem [0:MAX_DEPTH-1];
	logic [14:0]             epi_col_mem         [0:CAPTURES_PER_AXIS-1][0:MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Input memories : angular derivative stream
	// ------------------------------------------------------------------------
	logic                    ang_deriv_valid_mem       [0:MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] ang_deriv_column_idx_mem  [0:MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] ang_deriv_row_idx_mem     [0:MAX_DEPTH-1];
	logic                    ang_deriv_orientation_mem [0:MAX_DEPTH-1];
	logic signed [15:0]      ang_deriv_col_mem         [0:DERIVATIVE_COUNT-1][0:MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Driven DUT inputs
	// ------------------------------------------------------------------------
	logic                            epi_valid_in = 1'b0;
	logic [14:0]                     epi_column_in [0:CAPTURES_PER_AXIS-1];
	logic [IMAGE_DIM_BS-1:0]         epi_column_idx_in = '0;
	logic [IMAGE_DIM_BS-1:0]         epi_idx_in        = '0;
	logic                            epi_orientation_in = 1'b0;

	logic                            angular_derivative_valid_in = 1'b0;
	logic signed [15:0]              angular_derivative_column_in [0:DERIVATIVE_COUNT-1];
	logic [IMAGE_DIM_BS-1:0]         angular_derivative_row_idx_in = '0;
	logic [IMAGE_DIM_BS-1:0]         angular_derivative_column_idx_in = '0;
	logic                            angular_derivative_orientation_in = 1'b0;

	// ------------------------------------------------------------------------
	// DUT outputs
	// ------------------------------------------------------------------------
	logic                            disparity_valid_out;
	logic signed [31:0]              disparity_pixel_out;
	logic [IMAGE_DIM_BS-1:0]         disparity_row_idx_out;
	logic [IMAGE_DIM_BS-1:0]         disparity_column_idx_out;
	logic                            orientation_out;

	// ------------------------------------------------------------------------
	// DUT instantiation
	// ------------------------------------------------------------------------
	disparity_estimator #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) DUT (
		.clk(clkock_50_fix(clock_50)),

		.epi_valid_in(epi_valid_in),
		.epi_column_in(epi_column_in),
		.epi_column_idx_in(epi_column_idx_in),
		.epi_idx_in(epi_idx_in),
		.epi_orientation_in(epi_orientation_in),

		.angular_derivative_valid_in(angular_derivative_valid_in),
		.angular_derivative_column_in(angular_derivative_column_in),
		.angular_derivative_row_idx_in(angular_derivative_row_idx_in),
		.angular_derivative_column_idx_in(angular_derivative_column_idx_in),
		.angular_derivative_orientation_in(angular_derivative_orientation_in),

		.disparity_valid_out(disparity_valid_out),
		.disparity_pixel_out(disparity_pixel_out),
		.disparity_row_idx_out(disparity_row_idx_out),
		.disparity_column_idx_out(disparity_column_idx_out),
		.orientation_out(orientation_out)
	);

	function automatic logic clkock_50_fix(input logic c);
		clkock_50_fix = c;
	endfunction

	// ------------------------------------------------------------------------
	// Output capture memories : disparity
	// ------------------------------------------------------------------------
	logic                    out_disp_valid_mem       [0:OUT_MAX_DEPTH-1];
	logic                    out_disp_orientation_mem [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_disp_row_idx_mem     [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_disp_col_idx_mem     [0:OUT_MAX_DEPTH-1];
	logic signed [31:0]      out_disp_pixel_mem       [0:OUT_MAX_DEPTH-1];

	int out_idx;
	int OUT_DEPTH;

	// ------------------------------------------------------------------------
	// Helper: parse DEPTH=... from MIF header
	// ------------------------------------------------------------------------
	function automatic int read_depth_from_mif(string mif_path);
		int fd;
		string line;
		int d;
		int rc;

		d  = -1;
		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF to read depth: %s", mif_path);
		end

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			rc = $sscanf(line, "DEPTH=%d;", d);
			if (rc == 1) begin
				$fclose(fd);
				return d;
			end
		end

		$fclose(fd);
		$fatal(1, "ERROR: Could not find DEPTH=... in MIF header: %s", mif_path);
		return -1;
	endfunction

	// ------------------------------------------------------------------------
	// Load 1-bit MIF
	// ------------------------------------------------------------------------
	task automatic load_mif_1(
		input string mif_path,
		input int depth,
		output logic mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 1'b0;
		end

		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF: %s", mif_path);
		end

		in_content = 0;

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);

			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			addr = -1;
			data = 1'b0;
			rc = $sscanf(line, "%d : %b;", addr, data);

			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Load 7-bit MIF
	// ------------------------------------------------------------------------
	task automatic load_mif_7(
		input string mif_path,
		input int depth,
		output logic [IMAGE_DIM_BS-1:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic [IMAGE_DIM_BS-1:0] data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = '0;
		end

		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF: %s", mif_path);
		end

		in_content = 0;

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);

			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			addr = -1;
			data = '0;
			rc = $sscanf(line, "%d : %b;", addr, data);

			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Load 15-bit unsigned MIF
	// ------------------------------------------------------------------------
	task automatic load_mif_15(
		input string mif_path,
		input int depth,
		output logic [14:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic [14:0] data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 15'd0;
		end

		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF: %s", mif_path);
		end

		in_content = 0;

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);

			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			addr = -1;
			data = 15'd0;
			rc = $sscanf(line, "%d : %b;", addr, data);

			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Load 16-bit signed MIF
	// ------------------------------------------------------------------------
	task automatic load_mif_16_signed(
		input string mif_path,
		input int depth,
		output logic signed [15:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic signed [15:0] data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 16'sd0;
		end

		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF: %s", mif_path);
		end

		in_content = 0;

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);

			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			addr = -1;
			data = 16'sd0;
			rc = $sscanf(line, "%d : %b;", addr, data);

			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Write 1-bit MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_1_out(
		input string mif_path,
		input int depth,
		input logic mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=1;");
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %0b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Write 7-bit MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_7_out(
		input string mif_path,
		input int depth,
		input logic [IMAGE_DIM_BS-1:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=%0d;", IMAGE_DIM_BS);
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %07b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Write 32-bit signed MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_32_signed_out(
		input string mif_path,
		input int depth,
		input logic signed [31:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=32;");
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %032b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	function automatic string int_to_string(input int v);
		string s;
		$sformat(s, "%0d", v);
		return s;
	endfunction

	// ------------------------------------------------------------------------
	// Clear output memories
	// ------------------------------------------------------------------------
	task automatic clear_output_memories;
		begin
			out_idx   = 0;
			OUT_DEPTH = 0;

			for (int k = 0; k < OUT_MAX_DEPTH; k++) begin
				out_disp_valid_mem[k]       = 1'b0;
				out_disp_orientation_mem[k] = 1'b0;
				out_disp_row_idx_mem[k]     = '0;
				out_disp_col_idx_mem[k]     = '0;
				out_disp_pixel_mem[k]       = 32'sd0;
			end
		end
	endtask

	// ------------------------------------------------------------------------
	// Capture all outputs every cycle
	// ------------------------------------------------------------------------
	always_ff @(posedge clock_50) begin
		if (out_idx < OUT_MAX_DEPTH) begin
			out_disp_valid_mem[out_idx]       <= disparity_valid_out;
			out_disp_orientation_mem[out_idx] <= orientation_out;
			out_disp_row_idx_mem[out_idx]     <= disparity_row_idx_out;
			out_disp_col_idx_mem[out_idx]     <= disparity_column_idx_out;
			out_disp_pixel_mem[out_idx]       <= disparity_pixel_out;

			out_idx <= out_idx + 1;
		end
		else begin
			$fatal(1, "ERROR: Output capture overflow. Increase OUT_MAX_DEPTH.");
		end
	end

	// ------------------------------------------------------------------------
	// Main simulation
	// ------------------------------------------------------------------------
	int i;

	initial begin
		$dumpfile("dump_disp_est.vcd");
		$dumpvars(0, disparity_estimator_tb);

		DEPTH_EPI       = read_depth_from_mif(IN_EPI_VALID_MIF);
		DEPTH_ANG_DERIV = read_depth_from_mif(IN_ANG_DERIV_VALID_MIF);

		if (DEPTH_EPI <= 0) begin
			$fatal(1, "ERROR: EPI DEPTH read as %0d.", DEPTH_EPI);
		end

		if (DEPTH_ANG_DERIV <= 0) begin
			$fatal(1, "ERROR: ANGULAR DERIVATIVE DEPTH read as %0d.", DEPTH_ANG_DERIV);
		end

		DEPTH = DEPTH_EPI;

		if (DEPTH > MAX_DEPTH) begin
			$fatal(1, "ERROR: DEPTH=%0d exceeds MAX_DEPTH=%0d.", DEPTH, MAX_DEPTH);
		end

		if (DEPTH_ANG_DERIV > MAX_DEPTH) begin
			$fatal(1, "ERROR: DEPTH_ANG_DERIV=%0d exceeds MAX_DEPTH=%0d.", DEPTH_ANG_DERIV, MAX_DEPTH);
		end

		if (DEPTH_ANG_DERIV < (ANG_DERIV_TRIM_OFFSET + DEPTH)) begin
			$fatal(
				1,
				"ERROR: Angular derivative stream too short after trim. DEPTH_ANG_DERIV=%0d, required at least %0d.",
				DEPTH_ANG_DERIV,
				ANG_DERIV_TRIM_OFFSET + DEPTH
			);
		end

		$display("INFO: Loading disparity estimator input MIFs from: %s", IN_DIR);
		$display("INFO: EPI depth = %0d", DEPTH_EPI);
		$display("INFO: Angular derivative raw depth = %0d", DEPTH_ANG_DERIV);
		$display("INFO: Trimming first %0d angular-derivative cycles to align with EPI input stream.", ANG_DERIV_TRIM_OFFSET);

		// Load EPI stream
		load_mif_1(IN_EPI_VALID_MIF,       DEPTH_EPI, epi_valid_mem);
		load_mif_7(IN_EPI_COLUMN_IDX_MIF,  DEPTH_EPI, epi_column_idx_mem);
		load_mif_7(IN_EPI_IDX_MIF,         DEPTH_EPI, epi_idx_mem);
		load_mif_1(IN_EPI_ORIENTATION_MIF, DEPTH_EPI, epi_orientation_mem);

		for (int c = 0; c < CAPTURES_PER_AXIS; c++) begin
			load_mif_15({IN_DIR, "/SIM_EPI_COLUMN_IN_", int_to_string(c), ".mif"}, DEPTH_EPI, epi_col_mem[c]);
		end

		// Load angular derivative stream
		load_mif_1(IN_ANG_DERIV_VALID_MIF,       DEPTH_ANG_DERIV, ang_deriv_valid_mem);
		load_mif_7(IN_ANG_DERIV_COLUMN_IDX_MIF,  DEPTH_ANG_DERIV, ang_deriv_column_idx_mem);
		load_mif_7(IN_ANG_DERIV_ROW_IDX_MIF,     DEPTH_ANG_DERIV, ang_deriv_row_idx_mem);
		load_mif_1(IN_ANG_DERIV_ORIENTATION_MIF, DEPTH_ANG_DERIV, ang_deriv_orientation_mem);

		for (int c = 0; c < DERIVATIVE_COUNT; c++) begin
			load_mif_16_signed({IN_DIR, "/SIM_DERIVATIVE_COLUMN_OUT_", int_to_string(c), ".mif"}, DEPTH_ANG_DERIV, ang_deriv_col_mem[c]);
		end

		clear_output_memories();

		repeat (4) @(posedge clock_50);

		// Warm-up
		for (i = 0; i < WARMUP_CYCLES; i++) begin
			@(posedge clock_50);

			epi_valid_in       <= 1'b0;
			epi_column_idx_in  <= '0;
			epi_idx_in         <= '0;
			epi_orientation_in <= 1'b0;

			angular_derivative_valid_in       <= 1'b0;
			angular_derivative_row_idx_in     <= '0;
			angular_derivative_column_idx_in  <= '0;
			angular_derivative_orientation_in <= 1'b0;

			for (int c = 0; c < CAPTURES_PER_AXIS; c++) begin
				epi_column_in[c] <= 15'd0;
			end

			for (int c = 0; c < DERIVATIVE_COUNT; c++) begin
				angular_derivative_column_in[c] <= 16'sd0;
			end
		end

		// Drive aligned input stream
		for (i = 0; i < DEPTH; i++) begin
			@(posedge clock_50);

			epi_valid_in       <= epi_valid_mem[i];
			epi_column_idx_in  <= epi_column_idx_mem[i];
			epi_idx_in         <= epi_idx_mem[i];
			epi_orientation_in <= epi_orientation_mem[i];

			for (int c = 0; c < CAPTURES_PER_AXIS; c++) begin
				epi_column_in[c] <= epi_col_mem[c][i];
			end

			angular_derivative_valid_in       <= ang_deriv_valid_mem[i + ANG_DERIV_TRIM_OFFSET];
			angular_derivative_row_idx_in     <= ang_deriv_row_idx_mem[i + ANG_DERIV_TRIM_OFFSET];
			angular_derivative_column_idx_in  <= ang_deriv_column_idx_mem[i + ANG_DERIV_TRIM_OFFSET];
			angular_derivative_orientation_in <= ang_deriv_orientation_mem[i + ANG_DERIV_TRIM_OFFSET];

			for (int c = 0; c < DERIVATIVE_COUNT; c++) begin
				angular_derivative_column_in[c] <= ang_deriv_col_mem[c][i + ANG_DERIV_TRIM_OFFSET];
			end
		end

		// Tail drain
		for (i = 0; i < EXTRA_TAIL; i++) begin
			@(posedge clock_50);

			epi_valid_in       <= 1'b0;
			epi_column_idx_in  <= '0;
			epi_idx_in         <= '0;
			epi_orientation_in <= 1'b0;

			angular_derivative_valid_in       <= 1'b0;
			angular_derivative_row_idx_in     <= '0;
			angular_derivative_column_idx_in  <= '0;
			angular_derivative_orientation_in <= 1'b0;

			for (int c = 0; c < CAPTURES_PER_AXIS; c++) begin
				epi_column_in[c] <= 15'd0;
			end

			for (int c = 0; c < DERIVATIVE_COUNT; c++) begin
				angular_derivative_column_in[c] <= 16'sd0;
			end
		end

		@(posedge clock_50);

		OUT_DEPTH = out_idx;

		$display("INFO: Writing disparity_estimator outputs (depth=%0d) to %s", OUT_DEPTH, OUT_DIR);

		write_mif_1_out({OUT_DIR, "/", OUT_DISP_VALID_MIF},       OUT_DEPTH, out_disp_valid_mem);
		write_mif_1_out({OUT_DIR, "/", OUT_DISP_ORIENTATION_MIF}, OUT_DEPTH, out_disp_orientation_mem);
		write_mif_7_out({OUT_DIR, "/", OUT_DISP_ROW_IDX_MIF},     OUT_DEPTH, out_disp_row_idx_mem);
		write_mif_7_out({OUT_DIR, "/", OUT_DISP_COLUMN_IDX_MIF},  OUT_DEPTH, out_disp_col_idx_mem);
		write_mif_32_signed_out({OUT_DIR, "/", OUT_DISP_PIXEL_MIF}, OUT_DEPTH, out_disp_pixel_mem);

		$display("INFO: Disparity estimator testbench finished.");
		$finish;
	end

endmodule