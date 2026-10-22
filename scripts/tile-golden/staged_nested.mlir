cuda_tile.module @m {
  entry @staged_nested(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12 = constant <i32: 0> : tile<i32>
    %13 = constant <i32: 3> : tile<i32>
    %14 = constant <i32: 1> : tile<i32>
    %15 = for %16 in (%12 to %13, step %14) : tile<i32> iter_values(%17 = %7) -> (tile<128xf64>) {
      %18 = constant <i32: 2> : tile<i32>
      %19 = cmpi less_than %16, %18, signed : tile<i32> -> tile<i1>
      %20 = if %19 -> (tile<128xf64>) {
        %21 = constant <i32: 0> : tile<i32>
        %22 = cmpi equal %9, %21, signed : tile<i32> -> tile<i1>
        %23 = if %22 -> (tile<128xf64>) {
          %24 = addf %17, %7 rounding<nearest_even> : tile<128xf64>
          yield %24 : tile<128xf64>
        } else {
          %25 = constant <f64: 2.0> : tile<128xf64>
          %26 = mulf %7, %25 rounding<nearest_even> : tile<128xf64>
          %27 = addf %17, %26 rounding<nearest_even> : tile<128xf64>
          yield %27 : tile<128xf64>
        }
        yield %23 : tile<128xf64>
      } else {
        %28 = subf %17, %7 rounding<nearest_even> : tile<128xf64>
        yield %28 : tile<128xf64>
      }
      continue %20 : tile<128xf64>
    }
    %29 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %30 = make_tensor_view %29, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %31 = make_partition_view %30 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %32 = store_view_tko weak %15, %31[%4] token=%0 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
