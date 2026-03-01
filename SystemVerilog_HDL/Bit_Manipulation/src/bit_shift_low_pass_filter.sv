module bit_shift_low_pass_filter (
	input wire clk,
	input wire [1:0] kernel_size,
	input wire pixel_valid_in,
	input wire soc_in,
	input wire eoc_in,
	input wire solf_in,
	input wire eolf_in,
	input logic [23:0] pixel_in,
	output logic pixel_valid_out,
	output logic soc_out,
	output logic eoc_out,
	output logic solf_out,
	output logic eolf_out,
	output logic [23:0] pixel_out_red,
	output logic [23:0] pixel_out_green,
	output logic [23:0] pixel_out_blue
);

	// ---------- Define parameters and variables ----------
	localparam int unsigned IMAGE_DIM = 64;
	localparam int unsigned IMAGE_DIM_BS = 6; // 1 << 6 = 64

	// SW0 SW1 to kernel size
	// 00 -> 1 (No blur)
	// 01 -> 3
	// 10 -> 5
	// 11 -> 7

	// Define kernels
	localparam logic [1:0] kernel_3 [0:8] = '{
		0, 1, 0,
		1, 2, 1,
		0, 1, 0
	};								// >> 4, sum = 16

	localparam logic [1:0] kernel_5 [0:24] = '{
		0, 1, 1, 1, 0,
		1, 2, 2, 2, 1,
		1, 2, 2, 2, 1,
		1, 2, 2, 2, 1,
		0, 1, 1, 1, 0
	};								// >> 6, sum = 64

	localparam logic [1:0] kernel_7 [0:48] = '{
		0, 0, 1, 1, 1, 0, 0,
		0, 1, 2, 2, 2, 1, 0,
		1, 2, 2, 2, 2, 2, 1,
		1, 2, 2, 2, 2, 2, 1,
		1, 2, 2, 2, 2, 2, 1,
		0, 1, 2, 2, 2, 1, 0,
		0, 0, 1, 1, 1, 0, 0
	};								// >> 7, sum = 128
	
	// Flag to note that next start/end of capture is also start/end of light field
	logic next_soc_is_solf = 0;
	logic next_eoc_is_eolf = 0;

	// Initialise pixel buffer 
	// Assume 24 bit input has 8 bits per colour channel
	logic [7:0] pixel_buffer_red   [0:(6<<IMAGE_DIM_BS)+6];
	logic [7:0] pixel_buffer_green [0:(6<<IMAGE_DIM_BS)+6];
	logic [7:0] pixel_buffer_blue  [0:(6<<IMAGE_DIM_BS)+6];

	// Initialise pixel counters for image
	logic [IMAGE_DIM_BS-1:0] row_count    = 0;
	logic [IMAGE_DIM_BS-1:0] column_count = 0;

	// Buffer counter for filtered output lag
	localparam int unsigned LAG_BUFFER_MAX  = (6<<IMAGE_DIM_BS)+6;
	localparam int unsigned LAG_BUFFER_SIZE = $clog2(LAG_BUFFER_MAX+1);
	logic [LAG_BUFFER_SIZE-1:0] start_lag_buffer_count = 0;
	logic [LAG_BUFFER_SIZE-1:0] end_lag_buffer_count   = 0;

	// Flag raised for start/end of capture when corresponding lag buffer is full
	logic soc_lag_flag = 0;
	logic eoc_lag_flag = 0;

	// Pulse flags to ensure single time triggered event
	logic soc_out_pulse = 0;
	logic eoc_out_pulse = 0;

	// Break large pixel input data into each colour channel
	// pixel_in format is 24 bit RGB, presumably 8 bits per colour channel
	// The 24 bit RGB is assumed to be rectified as stated in EPI Module 1.1
	// We are using unsigned Q12.12
	logic [7:0] pixel_in_red;
	logic [7:0] pixel_in_green;
	logic [7:0] pixel_in_blue;
	
	assign pixel_in_red   = pixel_in[23:16];
	assign pixel_in_green = pixel_in[15:8];
	assign pixel_in_blue  = pixel_in[7:0];

	// Convoluted pixel variables [7+7:0] due to bit shift space
	logic [14:0] convoluted_red   = 0;
	logic [14:0] convoluted_green = 0;
	logic [14:0] convoluted_blue  = 0;
	
	// Flag to set all values to zero once
	logic set_outputs_initially_flag = 0;

	// Flag to determine if output should be convolved (1) or raw edge (0) pixel
	logic convolved_flag = 0;

	// ----------  Shift incoming pixels into separate RGB buffers ----------
	always_ff @(posedge clk) begin : Image_Buffer
		// Set buffers initially zero to avoid undefined signals
		if (!set_outputs_initially_flag) begin
			for (int idx = 0; idx < ((6<<IMAGE_DIM_BS)+7); idx++) begin
				pixel_buffer_red[idx]   <= 0;
				pixel_buffer_green[idx] <= 0;
				pixel_buffer_blue[idx]  <= 0;
			end
			
			set_outputs_initially_flag <= 1;
		end

		// Run this for every new capture
		if (soc_in) begin
			// Reset counters
			row_count    <= 0;
			column_count <= 0;

			// Reset start of capture lag flag and buffer
			soc_lag_flag           <= 0;
			start_lag_buffer_count <= 0;
		end

		// Logic to keep outputting until frame is complete
		// Keep adding new pixels to buffer, but continue outputting
		// Final pixels are not convolved and are taken from RGB buffers
		if (eoc_in) begin
			// Raise a flag to note that we need to keep outputting pixels until capture is complete
			eoc_lag_flag <= 1;

			// Reset buffer
			end_lag_buffer_count <= 0;
		end

		// Increment buffer and compare to expected full length to note that all capture pixels are outputted
		if (eoc_lag_flag) begin
			end_lag_buffer_count <= end_lag_buffer_count + $bits(end_lag_buffer_count)'(1);
			
			case(kernel_size)
				2'b00 : begin // None
					eoc_lag_flag  <= 0;
					eoc_out_pulse <= 1;
				end
				2'b01 : begin // 3x3
					if (end_lag_buffer_count == (2<<IMAGE_DIM_BS)+1) begin
						eoc_out_pulse <= 1;
					end
					if (end_lag_buffer_count == (2<<IMAGE_DIM_BS)+2) begin
						eoc_lag_flag  <= 0;
					end
				end
				2'b10 : begin // 5x5
					if (end_lag_buffer_count == (4<<IMAGE_DIM_BS)+3) begin
						eoc_out_pulse <= 1;
					end
					if (end_lag_buffer_count == (4<<IMAGE_DIM_BS)+4) begin
						eoc_lag_flag  <= 0;
					end
				end
				2'b11 : begin // 7x7
					if (end_lag_buffer_count == (6<<IMAGE_DIM_BS)+5) begin
						eoc_out_pulse <= 1;
					end
					if (end_lag_buffer_count == (6<<IMAGE_DIM_BS)+6) begin
						eoc_lag_flag  <= 0;
					end
				end
			endcase
		end

		// Run this when pixel is valid
		if (pixel_valid_in) begin
			// Shift all of the pixel buffers left
			for (int idx = 0; idx < ((6<<IMAGE_DIM_BS)+6); idx++) begin
				pixel_buffer_red[idx]   <= pixel_buffer_red[idx+1];
				pixel_buffer_green[idx] <= pixel_buffer_green[idx+1];
				pixel_buffer_blue[idx]  <= pixel_buffer_blue[idx+1];
			end

			case(kernel_size)
				2'b00 : begin // None
					soc_lag_flag  <= 1;
					soc_out_pulse <= 1;
				end

				2'b01 : begin // 3x3
					// Insert new pixel data at the end of buffer (FIFO)
					pixel_buffer_red[(2<<IMAGE_DIM_BS)+2]   <= pixel_in_red;
					pixel_buffer_green[(2<<IMAGE_DIM_BS)+2] <= pixel_in_green;
					pixel_buffer_blue[(2<<IMAGE_DIM_BS)+2]  <= pixel_in_blue;

					// Increment start buffer to account for output lag (pixel buffers full)
					if (!soc_lag_flag) begin
						start_lag_buffer_count <= start_lag_buffer_count + $bits(start_lag_buffer_count)'(1);
						if (start_lag_buffer_count == (2<<IMAGE_DIM_BS)+1) begin
							soc_lag_flag  <= 1;
							soc_out_pulse <= 1;
						end
					end
				end

				2'b10 : begin // 5x5
					// Insert new pixel data at the end of buffer (FIFO)
					pixel_buffer_red[(4<<IMAGE_DIM_BS)+4]   <= pixel_in_red;
					pixel_buffer_green[(4<<IMAGE_DIM_BS)+4] <= pixel_in_green;
					pixel_buffer_blue[(4<<IMAGE_DIM_BS)+4]  <= pixel_in_blue;

					// Increment start buffer to account for output lag (pixel buffers full)
					if (!soc_lag_flag) begin
						start_lag_buffer_count <= start_lag_buffer_count + $bits(start_lag_buffer_count)'(1);
						if (start_lag_buffer_count == (4<<IMAGE_DIM_BS)+3) begin
							soc_lag_flag <= 1;
							soc_out_pulse <= 1;
						end
					end
				end

				2'b11 : begin // 7x7
					// Insert new pixel data at the end of buffer (FIFO)
					pixel_buffer_red[(6<<IMAGE_DIM_BS)+6]   <= pixel_in_red;
					pixel_buffer_green[(6<<IMAGE_DIM_BS)+6] <= pixel_in_green;
					pixel_buffer_blue[(6<<IMAGE_DIM_BS)+6]  <= pixel_in_blue;

					// Increment start buffer to account for output lag (pixel buffers full)
					if (!soc_lag_flag) begin
						start_lag_buffer_count <= start_lag_buffer_count + $bits(start_lag_buffer_count)'(1);
						if (start_lag_buffer_count == (6<<IMAGE_DIM_BS)+5) begin
							soc_lag_flag  <= 1;
							soc_out_pulse <= 1;
						end
					end
				end
			endcase

			// When all columns in a row exhausted, start next row
			if (column_count == IMAGE_DIM-1) begin
				column_count <= 0;
				row_count    <= row_count + $bits(row_count)'(1);
			end

			// Increment column count for every new valid pixel
			else begin
				column_count <= column_count + $bits(column_count)'(1);
			end
		end

		// Reset pulse flags
		if (soc_out_pulse) begin 
			soc_out_pulse <= 0;
		end

		if (eoc_out_pulse) begin 
			eoc_out_pulse <= 0;
		end
	end

	// ---------- Apply low pass filter to blur image ----------
	always_ff @(posedge clk) begin: Convolution
		// Reset variables for every pixel
		convoluted_red   = 0;
		convoluted_green = 0;
		convoluted_blue  = 0;

		// Run this for every new light field
		if (solf_in) begin
			next_soc_is_solf <= 1;
		end
		
		// Run this for when light field is complete
		if (eolf_in) begin
			next_eoc_is_eolf <= 1;
		end

		case(kernel_size)
			// No blur
			2'b00 : begin
				soc_out  <= soc_in;
				eoc_out  <= eoc_in;
				solf_out <= solf_in;
				eolf_out <= eolf_in;

				// Since we are using Q12.12, and input pixels is 8 bit:
				// Shift by 12 (decimal part) + 4 (integer part) -> X << 16
				pixel_out_red   <= (pixel_in_red << 16);
				pixel_out_green <= (pixel_in_green << 16);
				pixel_out_blue  <= (pixel_in_blue << 16);

				// For no blur, pixel outputs are immediately valid if input is valid
				pixel_valid_out <= pixel_valid_in;
			end

			// Use 3x3 convolving kernel
			2'b01 : begin
				// Convolute RGB channels separately
				for (int kernel_row = 0; kernel_row < 3; kernel_row++) begin
					for (int kernel_column = 0; kernel_column < 3; kernel_column++) begin // ((kernel_row << 1) + kernel_row) is effectively 3 * kernel_row
						convoluted_red   = convoluted_red   + (pixel_buffer_red[(kernel_row << IMAGE_DIM_BS)   + kernel_column] << kernel_3[((kernel_row << 1) + kernel_row) + kernel_column]);
						convoluted_green = convoluted_green + (pixel_buffer_green[(kernel_row << IMAGE_DIM_BS) + kernel_column] << kernel_3[((kernel_row << 1) + kernel_row) + kernel_column]);
						convoluted_blue  = convoluted_blue  + (pixel_buffer_blue[(kernel_row << IMAGE_DIM_BS)  + kernel_column] << kernel_3[((kernel_row << 1) + kernel_row) + kernel_column]);
					end
				end

				// Decide on output pixel
				// For 3x3, edge pixels are not validly convolved, so output buffered pixel
				if ((row_count == 0) || (row_count == IMAGE_DIM-1) || (column_count == 0) || (column_count == IMAGE_DIM-1)) begin
					convolved_flag = 0;
				end

				else begin
					convolved_flag = 1;
				end
			end

			// Use 5x5 convolving kernel
			2'b10 : begin
				// Convolute RGB channels separately
				for (int kernel_row = 0; kernel_row < 5; kernel_row++) begin
					for (int kernel_column = 0; kernel_column < 5; kernel_column++) begin // ((kernel_row << 2) + kernel_row) is effectively 5 * kernel_row
						convoluted_red   = convoluted_red   + (pixel_buffer_red[(kernel_row << IMAGE_DIM_BS)   + kernel_column] << kernel_5[((kernel_row << 2) + kernel_row) + kernel_column]);
						convoluted_green = convoluted_green + (pixel_buffer_green[(kernel_row << IMAGE_DIM_BS) + kernel_column] << kernel_5[((kernel_row << 2) + kernel_row) + kernel_column]);
						convoluted_blue  = convoluted_blue  + (pixel_buffer_blue[(kernel_row << IMAGE_DIM_BS)  + kernel_column] << kernel_5[((kernel_row << 2) + kernel_row) + kernel_column]);
					end
				end

				// Decide on output pixel
				// For 5x5, edge 2 pixels are not validly convolved, so output buffered pixel
				if ((row_count < 2) || (row_count >= IMAGE_DIM-2) || (column_count < 2) || (column_count >= IMAGE_DIM-2)) begin
					convolved_flag = 0;
				end

				else begin
					convolved_flag = 1;
				end
			end

			// Use 7x7 convolving kernel
			2'b11 : begin
				// Convolute RGB channels separately
				for (int kernel_row = 0; kernel_row < 7; kernel_row++) begin
					for (int kernel_column = 0; kernel_column < 7; kernel_column++) begin // ((kernel_row << 3) - kernel_row) is effectively 7 * kernel_row
						convoluted_red   = convoluted_red   + (pixel_buffer_red[(kernel_row << IMAGE_DIM_BS)   + kernel_column] << kernel_7[((kernel_row << 3) - kernel_row) + kernel_column]);
						convoluted_green = convoluted_green + (pixel_buffer_green[(kernel_row << IMAGE_DIM_BS) + kernel_column] << kernel_7[((kernel_row << 3) - kernel_row) + kernel_column]);
						convoluted_blue  = convoluted_blue  + (pixel_buffer_blue[(kernel_row << IMAGE_DIM_BS)  + kernel_column] << kernel_7[((kernel_row << 3) - kernel_row) + kernel_column]);
					end
				end

				// Decide on output pixel
				// For 7x7, edge 3 pixels are not validly convolved, so output buffered pixel
				if ((row_count < 3) || (row_count >= IMAGE_DIM-3) || (column_count < 3) || (column_count >= IMAGE_DIM-3)) begin
					convolved_flag = 0;
				end

				else begin
					convolved_flag = 1;
				end
			end
		endcase

		if (!kernel_size == 2'b00) begin
			// Whilst each flag is up the pixel is garuanteed to be an edge (original) pixel or convolved pixel
			pixel_valid_out <= (soc_lag_flag || eoc_lag_flag);
			
			// Start of capture when lag buffer is full (for 3x3) but flag not raised
			// This ensures a single pulse soc_out when lag buffer fills
			soc_out <= ((soc_lag_flag) && (soc_out_pulse));

			// End of capture when lag buffer decremented and flag not yet updated
			// This ensures a single pulse soc_out when lag buffer empties
			eoc_out <= ((eoc_lag_flag) && (eoc_out_pulse));

			// If flag is raised, then the start/end of capture is also after start/end of light field
			solf_out <= (next_soc_is_solf && (soc_lag_flag) && (soc_out_pulse));
			eolf_out <= (next_eoc_is_eolf && (eoc_lag_flag) && (eoc_out_pulse));

			// Lower flags after use
			if (solf_out) begin
				next_soc_is_solf <= 0;
			end

			if (eolf_out) begin
				next_eoc_is_eolf <= 0;
			end

			if (convolved_flag) begin
				// For valid convolutions, convert convolved value to Q12.12
				// To get from 14 to 23, we shift by 9
				// This allows [23:12] to be integer and [11:0] to be fractional
				pixel_out_red   <= (convoluted_red << 9);
				pixel_out_green <= (convoluted_green << 9);
				pixel_out_blue  <= (convoluted_blue << 9);
			end

			else begin
				// Since we are using Q12.12, and input pixels is 8 bit:
				// Shift by 12 (decimal part) + 4 (integer part) -> X << 16
				pixel_out_red   <= (pixel_buffer_red[0] << 16);
				pixel_out_green <= (pixel_buffer_green[0] << 16);
				pixel_out_blue  <= (pixel_buffer_blue[0] << 16);
			end
		end
	end

endmodule // Fix buffer use correctly as for different kernels we need to start the shift not at [0]