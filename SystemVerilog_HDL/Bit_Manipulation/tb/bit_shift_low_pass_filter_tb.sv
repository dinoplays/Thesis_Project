`timescale 1ns/1ps

// Ensure Assignments > Settings > EDA Tool Settings > Simulation > Tool Name is "ModelSim-Altera"
// Navigate to ModelSim Altera:
//     Tool > Run Simulation Tool > RTL Simulation
// In the ModelSim Altera transcript, run:
/*
do Thesis_Project_Bit_Manipulation_run_bslpf_tb.do
*/

module bit_shift_low_pass_filter_tb;

	// ------------------------------------------------------------------------
	// Clock: 50 MHz => 20 ns period
	// ------------------------------------------------------------------------
	localparam int TCLK_NS = 20;

	logic clock_50 = 1'b0;

	// Clock generation: Every half-cycle, invert the signal
	always #(TCLK_NS/2) clock_50 = ~clock_50;

	// ------------------------------------------------------------------------
	// Input stream paths (your generator outputs)
	// ------------------------------------------------------------------------
	localparam string IN_DIR  = "/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/tb/input_data";
	localparam string OUT_DIR = "/home/daniel/Thesis_Project/SystemVerilog_HDL/Bit_Manipulation/tb/bslpf_output_data/3x3_filter";

	localparam string IN_PIXEL_MIF = {IN_DIR, "/SIM_PIXEL_BIT_DATA.mif"};
	localparam string IN_VALID_MIF = {IN_DIR, "/SIM_PIXEL_VALID_IN.mif"};
	localparam string IN_SOC_MIF   = {IN_DIR, "/SIM_SOC_IN.mif"};
	localparam string IN_EOC_MIF   = {IN_DIR, "/SIM_EOC_IN.mif"};
	localparam string IN_SOLF_MIF  = {IN_DIR, "/SIM_SOLF_IN.mif"};
	localparam string IN_EOLF_MIF  = {IN_DIR, "/SIM_EOLF_IN.mif"};

	// ------------------------------------------------------------------------
	// Stream bounds
	// ------------------------------------------------------------------------
	localparam int MAX_DEPTH = 88888;

	int DEPTH = 0;

	// Warm-up cycles:
	// To give some time before meaningful data enters
	localparam int WARMUP_CYCLES = 16;

	// ------------------------------------------------------------------------
	// Output capture length
	// ------------------------------------------------------------------------
	localparam int EXTRA_TAIL    = 2000;
	localparam int OUT_MAX_DEPTH = MAX_DEPTH + EXTRA_TAIL + 64; // safety margin

	// Output MIF filenames (written into OUT_DIR)
	localparam string OUT_VALID_MIF = "SIM_PIXEL_VALID_OUT.mif";
	localparam string OUT_SOC_MIF   = "SIM_SOC_OUT.mif";
	localparam string OUT_EOC_MIF   = "SIM_EOC_OUT.mif";
	localparam string OUT_SOLF_MIF  = "SIM_SOLF_OUT.mif";
	localparam string OUT_EOLF_MIF  = "SIM_EOLF_OUT.mif";

	localparam string OUT_RED_MIF   = "SIM_PIXEL_OUT_RED.mif";
	localparam string OUT_GREEN_MIF = "SIM_PIXEL_OUT_GREEN.mif";
	localparam string OUT_BLUE_MIF  = "SIM_PIXEL_OUT_BLUE.mif";

	// ------------------------------------------------------------------------
	// Stimulus memories (cycle-aligned across all 6)
	// ------------------------------------------------------------------------
	logic [23:0] pixel_mem [0:MAX_DEPTH-1];
	logic        valid_mem [0:MAX_DEPTH-1];
	logic        soc_mem   [0:MAX_DEPTH-1];
	logic        eoc_mem   [0:MAX_DEPTH-1];
	logic        solf_mem  [0:MAX_DEPTH-1];
	logic        eolf_mem  [0:MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Captured outputs (cycle-aligned, one entry per clock)
	// ------------------------------------------------------------------------
	logic        out_valid_mem [0:OUT_MAX_DEPTH-1];
	logic        out_soc_mem   [0:OUT_MAX_DEPTH-1];
	logic        out_eoc_mem   [0:OUT_MAX_DEPTH-1];
	logic        out_solf_mem  [0:OUT_MAX_DEPTH-1];
	logic        out_eolf_mem  [0:OUT_MAX_DEPTH-1];

	logic [23:0] out_red_mem   [0:OUT_MAX_DEPTH-1];
	logic [23:0] out_green_mem [0:OUT_MAX_DEPTH-1];
	logic [23:0] out_blue_mem  [0:OUT_MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Driven DUT inputs (MUST be logic because we drive them procedurally)
	// Always drive these to known values (never leave floating/undefined).
	// ------------------------------------------------------------------------
	logic [23:0] pixel_in       = 24'd0;
	logic        pixel_valid_in = 1'b0;
	logic        soc_in         = 1'b0;
	logic        eoc_in         = 1'b0;
	logic        solf_in        = 1'b0;
	logic        eolf_in        = 1'b0;

	// ------------------------------------------------------------------------
	// DUT outputs (these will still go X early if DUT internal buffers are X;
	// warm-up cycles above will quickly flush them to 0/known)
	// ------------------------------------------------------------------------
	logic        pixel_valid_out = 1'b0;
	logic        soc_out         = 1'b0;
	logic        eoc_out         = 1'b0;
	logic        solf_out        = 1'b0;
	logic        eolf_out        = 1'b0;

	logic [23:0] pixel_out_red   = 24'd0;
	logic [23:0] pixel_out_green = 24'd0;
	logic [23:0] pixel_out_blue  = 24'd0;

	// ------------------------------------------------------------------------
	// Kernel under test (change this to 00/01/10/11)
	// For now you only want 01.
	// ------------------------------------------------------------------------
	localparam logic [1:0] KERNEL = 2'b01;

	bit_shift_low_pass_filter DUT (
		.clk(clock_50),
		.kernel_size(KERNEL),
		.pixel_valid_in(pixel_valid_in),
		.soc_in(soc_in),
		.eoc_in(eoc_in),
		.solf_in(solf_in),
		.eolf_in(eolf_in),
		.pixel_in(pixel_in),
		.pixel_valid_out(pixel_valid_out),
		.soc_out(soc_out),
		.eoc_out(eoc_out),
		.solf_out(solf_out),
		.eolf_out(eolf_out),
		.pixel_out_red(pixel_out_red),
		.pixel_out_green(pixel_out_green),
		.pixel_out_blue(pixel_out_blue)
	);

	// ------------------------------------------------------------------------
	// Helper: parse DEPTH=... from MIF header
	// (No string.find because ModelSim 2020.1 is picky with that)
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
	// Load a Quartus/Intel .mif into a packed memory:
	// Supports lines like:
	//   CONTENT BEGIN
	//   0 : 010101;
	//   1 : 111000;
	//   END;
	// ------------------------------------------------------------------------
	task automatic load_mif_24(
		input string mif_path,
		input int depth,
		output logic [23:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic [23:0] data;
		bit in_content;

		// Pre-clear memory to 0 so anything not written is known (no X's)
		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 24'd0;
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

			// Detect "CONTENT BEGIN"
			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);
			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			// Stop at "END;"
			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			// Parse content line: "addr : bits;"
			addr = -1;
			data = 24'd0;
			rc = $sscanf(line, "%d : %b;", addr, data);
			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

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

		// Pre-clear memory to 0 so anything not written is known (no X's)
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

			// Detect "CONTENT BEGIN"
			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);
			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			// Stop at "END;"
			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			// Parse content line: "addr : bit;"
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
	// Write output MIFs (Quartus style)
	// ------------------------------------------------------------------------
	task automatic write_mif_1(
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

	task automatic write_mif_24(
		input string mif_path,
		input int depth,
		input logic [23:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=24;");
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %024b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Main sim
	// ------------------------------------------------------------------------
	int i;

	// Output capture indexing
	int out_idx;
	int OUT_DEPTH;

	initial begin
		// Always start known
		pixel_in       = 24'd0;
		pixel_valid_in = 1'b0;
		soc_in         = 1'b0;
		eoc_in         = 1'b0;
		solf_in        = 1'b0;
		eolf_in        = 1'b0;

		// Clear output capture memories
		for (int k = 0; k < OUT_MAX_DEPTH; k++) begin
			out_valid_mem[k] = 1'b0;
			out_soc_mem[k]   = 1'b0;
			out_eoc_mem[k]   = 1'b0;
			out_solf_mem[k]  = 1'b0;
			out_eolf_mem[k]  = 1'b0;

			out_red_mem[k]   = 24'd0;
			out_green_mem[k] = 24'd0;
			out_blue_mem[k]  = 24'd0;
		end

		// Waveform (portable VCD) - ModelSim also records .wlf internally
		$dumpfile("dump.vcd");
		$dumpvars(0, bit_shift_low_pass_filter_tb);

		// Read DEPTH from the pixel MIF
		DEPTH = read_depth_from_mif(IN_PIXEL_MIF);

		if (DEPTH <= 0) begin
			$fatal(1, "ERROR: DEPTH read as %0d (bad).", DEPTH);
		end

		if (DEPTH > MAX_DEPTH) begin
			$fatal(1, "ERROR: DEPTH=%0d exceeds MAX_DEPTH=%0d. Increase MAX_DEPTH.", DEPTH, MAX_DEPTH);
		end

		if ((DEPTH + WARMUP_CYCLES + EXTRA_TAIL) > OUT_MAX_DEPTH) begin
			$fatal(
				1,
				"ERROR: OUT_MAX_DEPTH too small. Need %0d but OUT_MAX_DEPTH=%0d.",
				(DEPTH + WARMUP_CYCLES + EXTRA_TAIL),
				OUT_MAX_DEPTH
			);
		end

		$display("INFO: Kernel=%b DEPTH=%0d", KERNEL, DEPTH);
		$display("INFO: Loading MIFs from: %s", IN_DIR);

		// Load the six aligned streams (REAL .mif parsing, not $readmemb)
		load_mif_24(IN_PIXEL_MIF, DEPTH, pixel_mem);
		load_mif_1 (IN_VALID_MIF, DEPTH, valid_mem);
		load_mif_1 (IN_SOC_MIF,   DEPTH, soc_mem);
		load_mif_1 (IN_EOC_MIF,   DEPTH, eoc_mem);
		load_mif_1 (IN_SOLF_MIF,  DEPTH, solf_mem);
		load_mif_1 (IN_EOLF_MIF,  DEPTH, eolf_mem);

		// Let everything settle
		repeat (4) @(posedge clock_50);

		out_idx   = 0;
		OUT_DEPTH = 0;

		// Warm-up cycles (kept as requested)
		for (i = 0; i < WARMUP_CYCLES; i++) begin
			@(posedge clock_50);

			// Drive zeros
			pixel_in       <= 24'd0;
			pixel_valid_in <= 1'b0;
			soc_in         <= 1'b0;
			eoc_in         <= 1'b0;
			solf_in        <= 1'b0;
			eolf_in        <= 1'b0;

			// Capture DUT outputs for this cycle
			out_valid_mem[out_idx] <= pixel_valid_out;
			out_soc_mem[out_idx]   <= soc_out;
			out_eoc_mem[out_idx]   <= eoc_out;
			out_solf_mem[out_idx]  <= solf_out;
			out_eolf_mem[out_idx]  <= eolf_out;

			out_red_mem[out_idx]   <= pixel_out_red;
			out_green_mem[out_idx] <= pixel_out_green;
			out_blue_mem[out_idx]  <= pixel_out_blue;

			out_idx <= out_idx + 1;
		end

		// Drive EXACTLY what your generator produced (including invalid gaps)
		for (i = 0; i < DEPTH; i++) begin
			@(posedge clock_50);

			// Drive inputs
			pixel_in       <= pixel_mem[i];
			pixel_valid_in <= valid_mem[i];
			soc_in         <= soc_mem[i];
			eoc_in         <= eoc_mem[i];
			solf_in        <= solf_mem[i];
			eolf_in        <= eolf_mem[i];

			// Capture DUT outputs for this cycle
			out_valid_mem[out_idx] <= pixel_valid_out;
			out_soc_mem[out_idx]   <= soc_out;
			out_eoc_mem[out_idx]   <= eoc_out;
			out_solf_mem[out_idx]  <= solf_out;
			out_eolf_mem[out_idx]  <= eolf_out;

			out_red_mem[out_idx]   <= pixel_out_red;
			out_green_mem[out_idx] <= pixel_out_green;
			out_blue_mem[out_idx]  <= pixel_out_blue;

			out_idx <= out_idx + 1;
		end

		// After stream ends, hold zeros and keep capturing (tail drain)
		for (i = 0; i < EXTRA_TAIL; i++) begin
			@(posedge clock_50);

			// Drive zeros
			pixel_in       <= 24'd0;
			pixel_valid_in <= 1'b0;
			soc_in         <= 1'b0;
			eoc_in         <= 1'b0;
			solf_in        <= 1'b0;
			eolf_in        <= 1'b0;

			// Capture DUT outputs for this cycle
			out_valid_mem[out_idx] <= pixel_valid_out;
			out_soc_mem[out_idx]   <= soc_out;
			out_eoc_mem[out_idx]   <= eoc_out;
			out_solf_mem[out_idx]  <= solf_out;
			out_eolf_mem[out_idx]  <= eolf_out;

			out_red_mem[out_idx]   <= pixel_out_red;
			out_green_mem[out_idx] <= pixel_out_green;
			out_blue_mem[out_idx]  <= pixel_out_blue;

			out_idx <= out_idx + 1;
		end

		OUT_DEPTH = out_idx;

		$display("INFO: Writing output MIFs (OUT_DEPTH=%0d) to: %s", OUT_DEPTH, OUT_DIR);

		write_mif_1({OUT_DIR, "/", OUT_VALID_MIF}, OUT_DEPTH, out_valid_mem);
		write_mif_1({OUT_DIR, "/", OUT_SOC_MIF},   OUT_DEPTH, out_soc_mem);
		write_mif_1({OUT_DIR, "/", OUT_EOC_MIF},   OUT_DEPTH, out_eoc_mem);
		write_mif_1({OUT_DIR, "/", OUT_SOLF_MIF},  OUT_DEPTH, out_solf_mem);
		write_mif_1({OUT_DIR, "/", OUT_EOLF_MIF},  OUT_DEPTH, out_eolf_mem);

		write_mif_24({OUT_DIR, "/", OUT_RED_MIF},   OUT_DEPTH, out_red_mem);
		write_mif_24({OUT_DIR, "/", OUT_GREEN_MIF}, OUT_DEPTH, out_green_mem);
		write_mif_24({OUT_DIR, "/", OUT_BLUE_MIF},  OUT_DEPTH, out_blue_mem);

		$display("INFO: Finished waveform capture + MIF writes.");
		$display("INFO: VCD = dump.vcd");
		$finish;
	end

endmodule