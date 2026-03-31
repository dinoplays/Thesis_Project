`timescale 1ns/1ps

// Ensure Assignments > Settings > EDA Tool Settings > Simulation > Tool Name is "ModelSim-Altera"
// Navigate to ModelSim Altera:
//     Tool > Run Simulation Tool > RTL Simulation
// In the ModelSim Altera transcript, run:
/*
do Thesis_Project_Bit_Manipulation_run_confcomp_tb.do
*/

module confidence_computer_tb;

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
	localparam string IN_DIR  = "/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Bit_Manipulation/tb/conf_comp/input_data";
	localparam string OUT_DIR = "/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Bit_Manipulation/tb/conf_comp/output_data";

	localparam string IN_VALID_MIF       = {IN_DIR, "/SIM_EPI_VALID_IN.mif"};
	localparam string IN_COLUMN_IDX_MIF  = {IN_DIR, "/SIM_EPI_COLUMN_IDX_IN.mif"};
	localparam string IN_EPI_IDX_MIF     = {IN_DIR, "/SIM_EPI_IDX_IN.mif"};
	localparam string IN_ORIENTATION_MIF = {IN_DIR, "/SIM_ORIENTATION_IN.mif"};

	// ------------------------------------------------------------------------
	// Output filenames : derivative
	// ------------------------------------------------------------------------
	localparam string OUT_DERIV_VALID_MIF       = "SIM_DERIVATIVE_VALID_OUT.mif";
	localparam string OUT_DERIV_COLUMN_IDX_MIF  = "SIM_DERIVATIVE_COLUMN_IDX_OUT.mif";
	localparam string OUT_DERIV_IDX_MIF         = "SIM_DERIVATIVE_ROW_IDX_OUT.mif";
	localparam string OUT_DERIV_ORIENTATION_MIF = "SIM_DERIVATIVE_ORIENTATION_OUT.mif";

	// ------------------------------------------------------------------------
	// Output filenames : confidence
	// ------------------------------------------------------------------------
	localparam string OUT_CONF_VALID_MIF       = "SIM_CONF_VALID_OUT.mif";
	localparam string OUT_CONF_PIXEL_MIF       = "SIM_CONF_PIXEL_OUT.mif";
	localparam string OUT_CONF_ROW_IDX_MIF     = "SIM_CONF_ROW_IDX_OUT.mif";
	localparam string OUT_CONF_COLUMN_IDX_MIF  = "SIM_CONF_COLUMN_IDX_OUT.mif";
	localparam string OUT_CONF_ORIENTATION_MIF = "SIM_CONF_ORIENTATION_OUT.mif";

	// ------------------------------------------------------------------------
	// Depth / sizes
	// ------------------------------------------------------------------------
	localparam int VERTICAL_POST_FRAME_CYCLES = (IMAGE_DIM * IMAGE_DIM);
	localparam int EXTRA_TAIL    = VERTICAL_POST_FRAME_CYCLES;
	localparam int MAX_DEPTH     = 353000 + EXTRA_TAIL;
	localparam int WARMUP_CYCLES = 8;
	localparam int OUT_MAX_DEPTH = 4 + WARMUP_CYCLES + MAX_DEPTH + EXTRA_TAIL + 64;

	int DEPTH = 0;

	// ------------------------------------------------------------------------
	// Input memories
	// ------------------------------------------------------------------------
	logic                    valid_mem       [0:MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] column_idx_mem  [0:MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] epi_idx_mem     [0:MAX_DEPTH-1];
	logic                    orientation_mem [0:MAX_DEPTH-1];
	logic [14:0]             epi_col_mem     [0:CAPTURES_PER_AXIS-1][0:MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Driven DUT inputs
	// ------------------------------------------------------------------------
	logic                            epi_valid_in      = 1'b0;
	logic [14:0]                     epi_column_in [0:CAPTURES_PER_AXIS-1];
	logic [IMAGE_DIM_BS-1:0]         epi_column_idx_in = '0;
	logic [IMAGE_DIM_BS-1:0]         epi_idx_in        = '0;
	logic                            orientation_in    = 1'b0;

	// ------------------------------------------------------------------------
	// DUT outputs
	// ------------------------------------------------------------------------
	logic                            derivative_valid_out;
	logic signed [15:0]              derivative_column_out [0:DERIVATIVE_COUNT-1];
	logic [IMAGE_DIM_BS-1:0]         derivative_column_idx_out;
	logic [IMAGE_DIM_BS-1:0]         derivative_row_idx_out;
	logic                            derivative_orientation_out;

	logic                            confidence_valid_out;
	logic [14:0]                     confidence_pixel_out;
	logic [IMAGE_DIM_BS-1:0]         confidence_row_idx_out;
	logic [IMAGE_DIM_BS-1:0]         confidence_column_idx_out;
	logic                            confidence_orientation_out;

	// ------------------------------------------------------------------------
	// DUT instantiation
	// ------------------------------------------------------------------------
	confidence_computer #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) DUT (
		.clk(clkock_50_fix(clock_50)),
		.epi_valid_in(epi_valid_in),
		.epi_column_in(epi_column_in),
		.epi_column_idx_in(epi_column_idx_in),
		.epi_idx_in(epi_idx_in),
		.orientation_in(orientation_in),

		.derivative_valid_out(derivative_valid_out),
		.derivative_column_out(derivative_column_out),
		.derivative_row_idx_out(derivative_row_idx_out),
		.derivative_column_idx_out(derivative_column_idx_out),
		.derivative_orientation_out(derivative_orientation_out),

		.confidence_valid_out(confidence_valid_out),
		.confidence_pixel_out(confidence_pixel_out),
		.confidence_row_idx_out(confidence_row_idx_out),
		.confidence_column_idx_out(confidence_column_idx_out),
		.confidence_orientation_out(confidence_orientation_out)
	);

	function automatic logic clkock_50_fix(input logic c);
		clkock_50_fix = c;
	endfunction

	// ------------------------------------------------------------------------
	// Output capture memories : derivative
	// ------------------------------------------------------------------------
	logic                    out_deriv_valid_mem       [0:OUT_MAX_DEPTH-1];
	logic                    out_deriv_orientation_mem [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_deriv_col_idx_mem     [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_deriv_idx_mem         [0:OUT_MAX_DEPTH-1];
	logic signed [15:0]      out_deriv_col_mem         [0:DERIVATIVE_COUNT-1][0:OUT_MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Output capture memories : confidence
	// ------------------------------------------------------------------------
	logic                    out_conf_valid_mem       [0:OUT_MAX_DEPTH-1];
	logic                    out_conf_orientation_mem [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_conf_row_idx_mem     [0:OUT_MAX_DEPTH-1];
	logic [IMAGE_DIM_BS-1:0] out_conf_col_idx_mem     [0:OUT_MAX_DEPTH-1];
	logic [14:0]             out_conf_pixel_mem       [0:OUT_MAX_DEPTH-1];

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
	// Load 15-bit MIF
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
	// Write 15-bit unsigned MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_15_out(
		input string mif_path,
		input int depth,
		input logic [14:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=15;");
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %015b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Write 16-bit signed MIF
	// ------------------------------------------------------------------------
	task automatic write_mif_16_out(
		input string mif_path,
		input int depth,
		input logic signed [15:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=16;");
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %016b;", a, mem[a]);
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
				out_deriv_valid_mem[k]       = 1'b0;
				out_deriv_orientation_mem[k] = 1'b0;
				out_deriv_col_idx_mem[k]     = '0;
				out_deriv_idx_mem[k]         = '0;

				out_conf_valid_mem[k]        = 1'b0;
				out_conf_orientation_mem[k]  = 1'b0;
				out_conf_row_idx_mem[k]      = '0;
				out_conf_col_idx_mem[k]      = '0;
				out_conf_pixel_mem[k]        = 15'd0;
			end

			for (int c = 0; c < DERIVATIVE_COUNT; c++) begin
				for (int k = 0; k < OUT_MAX_DEPTH; k++) begin
					out_deriv_col_mem[c][k] = '0;
				end
			end
		end
	endtask

	// ------------------------------------------------------------------------
	// Capture ALL outputs every cycle
	// ------------------------------------------------------------------------
	always_ff @(posedge clock_50) begin
		if (out_idx < OUT_MAX_DEPTH) begin
			out_deriv_valid_mem[out_idx]       <= derivative_valid_out;
			out_deriv_orientation_mem[out_idx] <= derivative_orientation_out;
			out_deriv_col_idx_mem[out_idx]     <= derivative_column_idx_out;
			out_deriv_idx_mem[out_idx]         <= derivative_row_idx_out;

			for (int c = 0; c < DERIVATIVE_COUNT; c++) begin
				out_deriv_col_mem[c][out_idx] <= derivative_column_out[c];
			end

			out_conf_valid_mem[out_idx]       <= confidence_valid_out;
			out_conf_orientation_mem[out_idx] <= confidence_orientation_out;
			out_conf_row_idx_mem[out_idx]     <= confidence_row_idx_out;
			out_conf_col_idx_mem[out_idx]     <= confidence_column_idx_out;
			out_conf_pixel_mem[out_idx]       <= confidence_pixel_out;

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
		$dumpfile("dump_conf_comp.vcd");
		$dumpvars(0, confidence_computer_tb);

		DEPTH = read_depth_from_mif(IN_VALID_MIF);

		if (DEPTH <= 0) begin
			$fatal(1, "ERROR: DEPTH read as %0d.", DEPTH);
		end

		if (DEPTH > MAX_DEPTH) begin
			$fatal(1, "ERROR: DEPTH=%0d exceeds MAX_DEPTH=%0d.", DEPTH, MAX_DEPTH);
		end

		$display("INFO: Loading confidence computer input MIFs from: %s", IN_DIR);

		load_mif_1(IN_VALID_MIF,       DEPTH, valid_mem);
		load_mif_7(IN_COLUMN_IDX_MIF,  DEPTH, column_idx_mem);
		load_mif_7(IN_EPI_IDX_MIF,     DEPTH, epi_idx_mem);
		load_mif_1(IN_ORIENTATION_MIF, DEPTH, orientation_mem);

		for (int c = 0; c < CAPTURES_PER_AXIS; c++) begin
			load_mif_15({IN_DIR, "/SIM_EPI_COLUMN_IN_", int_to_string(c), ".mif"}, DEPTH, epi_col_mem[c]);
		end

		clear_output_memories();

		repeat (4) @(posedge clock_50);

		for (i = 0; i < WARMUP_CYCLES; i++) begin
			@(posedge clock_50);

			epi_valid_in      <= 1'b0;
			epi_column_idx_in <= '0;
			epi_idx_in        <= '0;
			orientation_in    <= 1'b0;

			for (int c = 0; c < CAPTURES_PER_AXIS; c++) begin
				epi_column_in[c] <= 15'd0;
			end
		end

		for (i = 0; i < DEPTH; i++) begin
			@(posedge clock_50);

			epi_valid_in      <= valid_mem[i];
			epi_column_idx_in <= column_idx_mem[i];
			epi_idx_in        <= epi_idx_mem[i];
			orientation_in    <= orientation_mem[i];

			for (int c = 0; c < CAPTURES_PER_AXIS; c++) begin
				epi_column_in[c] <= epi_col_mem[c][i];
			end
		end

		for (i = 0; i < EXTRA_TAIL; i++) begin
			@(posedge clock_50);

			epi_valid_in      <= 1'b0;
			epi_column_idx_in <= '0;
			epi_idx_in        <= '0;
			orientation_in    <= 1'b0;

			for (int c = 0; c < CAPTURES_PER_AXIS; c++) begin
				epi_column_in[c] <= 15'd0;
			end
		end

		@(posedge clock_50);

		OUT_DEPTH = out_idx;

		$display("INFO: Writing derivative_row_idx_out outputs (depth=%0d) to %s", OUT_DEPTH, OUT_DIR);

		// Derivative
		write_mif_1_out({OUT_DIR, "/", OUT_DERIV_VALID_MIF},       OUT_DEPTH, out_deriv_valid_mem);
		write_mif_1_out({OUT_DIR, "/", OUT_DERIV_ORIENTATION_MIF}, OUT_DEPTH, out_deriv_orientation_mem);
		write_mif_7_out({OUT_DIR, "/", OUT_DERIV_COLUMN_IDX_MIF},  OUT_DEPTH, out_deriv_col_idx_mem);
		write_mif_7_out({OUT_DIR, "/", OUT_DERIV_IDX_MIF},         OUT_DEPTH, out_deriv_idx_mem);

		for (int c = 0; c < DERIVATIVE_COUNT; c++) begin
			write_mif_16_out(
				{OUT_DIR, "/SIM_DERIVATIVE_COLUMN_OUT_", int_to_string(c), ".mif"},
				OUT_DEPTH,
				out_deriv_col_mem[c]
			);
		end

		// Confidence
		write_mif_1_out({OUT_DIR, "/", OUT_CONF_VALID_MIF},       OUT_DEPTH, out_conf_valid_mem);
		write_mif_1_out({OUT_DIR, "/", OUT_CONF_ORIENTATION_MIF}, OUT_DEPTH, out_conf_orientation_mem);
		write_mif_7_out({OUT_DIR, "/", OUT_CONF_ROW_IDX_MIF},     OUT_DEPTH, out_conf_row_idx_mem);
		write_mif_7_out({OUT_DIR, "/", OUT_CONF_COLUMN_IDX_MIF},  OUT_DEPTH, out_conf_col_idx_mem);
		write_mif_15_out({OUT_DIR, "/", OUT_CONF_PIXEL_MIF},      OUT_DEPTH, out_conf_pixel_mem);

		$display("INFO: Confidence computer testbench finished.");
		$finish;
	end

endmodule