cuda_tile.module @m {
  entry @gae(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 64> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<64xi32>
    %8 = iota : tile<64xi32>
    %9 = addi %7, %8 : tile<64xi32>
    %10 = constant <i32: 1> : tile<64xi32>
    %11 = addi %9, %10 : tile<64xi32>
    %12 = constant <i32: 255> : tile<64xi32>
    %13 = andi %11, %12 : tile<64xi32>
    %14 = constant <i32: 0> : tile<i32>
    %15 = reshape %14 : tile<i32> -> tile<1xi32>
    %16 = broadcast %15 : tile<1xi32> -> tile<64xi32>
    %17 = iota : tile<64xi32>
    %18 = addi %16, %17 : tile<64xi32>
    %19 = constant <i32: 0> : tile<64xi32>
    %20 = cmpi greater_than_or_equal %18, %19, signed : tile<64xi32> -> tile<64xi1>
    %21 = constant <i32: 63> : tile<64xi32>
    %22 = cmpi less_than %18, %21, signed : tile<64xi32> -> tile<64xi1>
    %23 = constant <i1: 0> : tile<64xi1>
    %24 = select %20, %22, %23 : tile<64xi1>, tile<64xi1>
    %25 = constant <f64: 0.0> : tile<64xf64>
    %26 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %27 = broadcast %26 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %28 = offset %27, %13 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %29, %30 = load_ptr_tko weak %28, %24, %25 token=%0 : tile<64xptr<f64>>, tile<64xi1>, tile<64xf64> -> tile<64xf64>, token
    %31 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %32 = make_tensor_view %31, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %33 = make_partition_view %32 : partition_view<tile=(64), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %34, %35, %36 = get_tile_block_id : tile<i32>
    %37, %38 = load_view_tko weak %33[%34] token=%30 : partition_view<tile=(64), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf64>, token
    %39 = constant <f64: 0.99> : tile<64xf64>
    %40 = mulf %39, %29 rounding<nearest_even> : tile<64xf64>
    %41 = addf %37, %40 rounding<nearest_even> : tile<64xf64>
    %42 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %43 = make_tensor_view %42, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %44 = make_partition_view %43 : partition_view<tile=(64), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %45, %46 = load_view_tko weak %44[%34] token=%38 : partition_view<tile=(64), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf64>, token
    %47 = subf %41, %45 rounding<nearest_even> : tile<64xf64>
    %48 = constant <f64: 0.9405> : tile<64xf64>
    %49, %50 = scan %48, %47 dim=0 reverse=true identities=[1.0 : f64, 0.0 : f64] : tile<64xf64>, tile<64xf64> -> tile<64xf64>, tile<64xf64> (%51: tile<f64>, %52: tile<f64>, %53: tile<f64>, %54: tile<f64>) {
      %55 = mulf %52, %51 rounding<nearest_even> : tile<f64>
      %56 = fma %52, %53, %54 rounding<nearest_even> : tile<f64>
      yield %55, %56 : tile<f64>, tile<f64>
    }
    %57 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %58 = make_tensor_view %57, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %59 = make_partition_view %58 : partition_view<tile=(64), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %60 = store_view_tko weak %50, %59[%34] token=%46 : tile<64xf64>, partition_view<tile=(64), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
