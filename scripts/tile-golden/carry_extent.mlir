cuda_tile.module @m {
  entry @carry_extent(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %3 = make_tensor_view %2, shape = [256, 128], strides = [128, 1] : tensor_view<256x128xf64, strides=[128, 1]>
    %4 = make_partition_view %3 : partition_view<tile=(64x128), padding_value = zero, tensor_view<256x128xf64, strides=[128, 1]>, dim_map=[0, 1]>
    %5, %6 = load_view_tko weak %4[%1, %1] token=%0 : partition_view<tile=(64x128), padding_value = zero, tensor_view<256x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x128xf64>, token
    %7 = reduce %5 dim=0 identities=[-Infinity : f64] : tile<64x128xf64> -> tile<128xf64> (%8: tile<f64>, %9: tile<f64>) {
      %10 = maxf %8, %9 : tile<f64>
      yield %10 : tile<f64>
    }
    %11 = constant <f64: 0.0> : tile<128xf64>
    %12 = constant <i32: 1> : tile<i32>
    %13 = constant <i32: 4> : tile<i32>
    %14 = constant <i32: 1> : tile<i32>
    %15, %16, %17 = for %18 in (%12 to %13, step %14) : tile<i32> iter_values(%19 = %7, %20 = %11, %21 = %6) -> (tile<128xf64>, tile<128xf64>, token) {
      %22, %23 = load_view_tko weak %4[%18, %1] token=%21 : partition_view<tile=(64x128), padding_value = zero, tensor_view<256x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x128xf64>, token
      %24 = reduce %22 dim=0 identities=[-Infinity : f64] : tile<64x128xf64> -> tile<128xf64> (%25: tile<f64>, %26: tile<f64>) {
        %27 = maxf %25, %26 : tile<f64>
        yield %27 : tile<f64>
      }
      %28 = constant <i32: 2> : tile<i32>
      %29 = cmpi less_than %18, %28, signed : tile<i32> -> tile<i1>
      %30 = if %29 -> (tile<128xf64>) {
        %31 = maxf %19, %24 : tile<128xf64>
        yield %31 : tile<128xf64>
      } else {
        yield %19 : tile<128xf64>
      }
      %32 = addf %20, %24 rounding<nearest_even> : tile<128xf64>
      continue %30, %32, %23 : tile<128xf64>, tile<128xf64>, token
    }
    %33, %34, %35 = get_num_tile_blocks : tile<i32>
    %36 = constant <i32: 128> : tile<i32>
    %37 = muli %33, %36 : tile<i32>
    %38 = itof %37 signed rounding<nearest_even> : tile<i32> -> tile<f64>
    %39 = reshape %38 : tile<f64> -> tile<1xf64>
    %40 = broadcast %39 : tile<1xf64> -> tile<128xf64>
    %41 = divf %16, %40 rounding<nearest_even> : tile<128xf64>
    %42 = addf %41, %15 rounding<nearest_even> : tile<128xf64>
    %43, %44, %45 = get_num_tile_blocks : tile<i32>
    %46 = constant <i32: 128> : tile<i32>
    %47 = muli %43, %46 : tile<i32>
    %48 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %49 = make_tensor_view %48, shape = [%47], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %50 = make_partition_view %49 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %51, %52, %53 = get_tile_block_id : tile<i32>
    %54 = store_view_tko weak %42, %50[%51] token=%17 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
