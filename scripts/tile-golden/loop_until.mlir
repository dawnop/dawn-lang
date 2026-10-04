cuda_tile.module @m {
  entry @loop_until(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [128], strides = [1] : tensor_view<128xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = constant <f64: 1.0> : tile<128xf64>
    %10 = constant <f64: 0.0> : tile<128xf64>
    %11, %12, %13 = loop iter_values(%14 = %9, %15 = %10, %16 = %8) : tile<128xf64>, tile<128xf64>, token -> (tile<128xf64>, tile<128xf64>, token) {
      %17 = mulf %14, %14 rounding<nearest_even> : tile<128xf64>
      %18 = subf %17, %7 rounding<nearest_even> : tile<128xf64>
      %19 = absf %18 : tile<128xf64>
      %20 = reduce %19 dim=0 identities=[-Infinity : f64] : tile<128xf64> -> tile<f64> (%21: tile<f64>, %22: tile<f64>) {
        %23 = maxf %21, %22 : tile<f64>
        yield %23 : tile<f64>
      }
      %24 = divf %7, %14 rounding<nearest_even> : tile<128xf64>
      %25 = addf %14, %24 rounding<nearest_even> : tile<128xf64>
      %26 = constant <f64: 0.5> : tile<128xf64>
      %27 = mulf %26, %25 rounding<nearest_even> : tile<128xf64>
      %28 = constant <f64: 1.0E-12> : tile<f64>
      %29 = cmpf greater_than ordered %28, %20 : tile<f64> -> tile<i1>
      %30 = constant <f64: 1.0> : tile<128xf64>
      %31 = addf %15, %30 rounding<nearest_even> : tile<128xf64>
      if %29 {
        break %14, %15, %16 : tile<128xf64>, tile<128xf64>, token
      } else {
        yield
      }
      continue %27, %31, %16 : tile<128xf64>, tile<128xf64>, token
    }
    %32 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %33 = make_tensor_view %32, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %34 = make_partition_view %33 : partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %35 = constant <i32: 2> : tile<i32>
    %36 = muli %4, %35 : tile<i32>
    %37 = store_view_tko weak %11, %34[%36] token=%13 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %38 = constant <i32: 2> : tile<i32>
    %39 = muli %4, %38 : tile<i32>
    %40 = constant <i32: 1> : tile<i32>
    %41 = addi %39, %40 : tile<i32>
    %42 = store_view_tko weak %12, %34[%41] token=%37 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
