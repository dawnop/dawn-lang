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
    %15, %16 = for %17 in (%12 to %13, step %14) : tile<i32> iter_values(%18 = %7, %19 = %11) -> (tile<128xf64>, tile<128xf64>) {
      %20, %21 = load_view_tko weak %4[%17, %1] token=%0 : partition_view<tile=(64x128), padding_value = zero, tensor_view<256x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x128xf64>, token
      %22 = reduce %20 dim=0 identities=[-Infinity : f64] : tile<64x128xf64> -> tile<128xf64> (%23: tile<f64>, %24: tile<f64>) {
        %25 = maxf %23, %24 : tile<f64>
        yield %25 : tile<f64>
      }
      %26 = constant <i32: 2> : tile<i32>
      %27 = cmpi less_than %17, %26, signed : tile<i32> -> tile<i1>
      %28 = if %27 -> (tile<128xf64>) {
        %29 = maxf %18, %22 : tile<128xf64>
        yield %29 : tile<128xf64>
      } else {
        yield %18 : tile<128xf64>
      }
      %30 = addf %19, %22 rounding<nearest_even> : tile<128xf64>
      continue %28, %30 : tile<128xf64>, tile<128xf64>
    }
    %31, %32, %33 = get_num_tile_blocks : tile<i32>
    %34 = constant <i32: 128> : tile<i32>
    %35 = muli %31, %34 : tile<i32>
    %36 = itof %35 signed rounding<nearest_even> : tile<i32> -> tile<f64>
    %37 = reshape %36 : tile<f64> -> tile<1xf64>
    %38 = broadcast %37 : tile<1xf64> -> tile<128xf64>
    %39 = divf %16, %38 rounding<nearest_even> : tile<128xf64>
    %40 = addf %39, %15 rounding<nearest_even> : tile<128xf64>
    %41, %42, %43 = get_num_tile_blocks : tile<i32>
    %44 = constant <i32: 128> : tile<i32>
    %45 = muli %41, %44 : tile<i32>
    %46 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %47 = make_tensor_view %46, shape = [%45], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %48 = make_partition_view %47 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %49, %50, %51 = get_tile_block_id : tile<i32>
    %52 = store_view_tko weak %40, %48[%49] token=%0 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
