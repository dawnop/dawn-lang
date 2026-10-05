cuda_tile.module @m {
  entry @attr_ftof(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %14 = ftof %12 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %15 = ftof %14 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %16 = reshape %15 : tile<128xf64> -> tile<1x1x128xf64>
    %17, %18, %19 = get_num_tile_blocks : tile<i32>
    %20 = constant <i32: 1> : tile<i32>
    %21 = muli %17, %20 : tile<i32>
    %22 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %23 = make_tensor_view %22, shape = [%21, 11, 128], strides = [1408, 128, 1] : tile<i32> -> tensor_view<?x11x128xf64, strides=[1408, 128, 1]>
    %24 = make_partition_view %23 : partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x11x128xf64, strides=[1408, 128, 1]>, dim_map=[0, 1, 2]>
    %25, %26, %27 = get_tile_block_id : tile<i32>
    %28, %29, %30 = get_tile_block_id : tile<i32>
    %31 = constant <i32: 16> : tile<i32>
    %32 = muli %26, %31 : tile<i32>
    %33 = store_view_tko weak %16, %24[%9, %32, %30] token=%13 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x11x128xf64, strides=[1408, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %34 = ftof %12 rounding<zero> : tile<128xf64> -> tile<128xf32>
    %35 = ftof %34 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %36 = reshape %35 : tile<128xf64> -> tile<1x1x128xf64>
    %37 = constant <i32: 16> : tile<i32>
    %38 = muli %26, %37 : tile<i32>
    %39 = constant <i32: 1> : tile<i32>
    %40 = addi %38, %39 : tile<i32>
    %41 = store_view_tko weak %36, %24[%9, %40, %30] token=%33 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x11x128xf64, strides=[1408, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %42 = ftof %12 rounding<negative_inf> : tile<128xf64> -> tile<128xf32>
    %43 = ftof %42 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %44 = reshape %43 : tile<128xf64> -> tile<1x1x128xf64>
    %45 = constant <i32: 16> : tile<i32>
    %46 = muli %26, %45 : tile<i32>
    %47 = constant <i32: 2> : tile<i32>
    %48 = addi %46, %47 : tile<i32>
    %49 = store_view_tko weak %44, %24[%9, %48, %30] token=%41 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x11x128xf64, strides=[1408, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %50 = ftof %12 rounding<positive_inf> : tile<128xf64> -> tile<128xf32>
    %51 = ftof %50 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %52 = reshape %51 : tile<128xf64> -> tile<1x1x128xf64>
    %53 = constant <i32: 16> : tile<i32>
    %54 = muli %26, %53 : tile<i32>
    %55 = constant <i32: 3> : tile<i32>
    %56 = addi %54, %55 : tile<i32>
    %57 = store_view_tko weak %52, %24[%9, %56, %30] token=%49 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x11x128xf64, strides=[1408, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %58 = ftof %14 rounding<nearest_even> : tile<128xf32> -> tile<128xtf32>
    %59 = ftof %58 rounding<nearest_even> : tile<128xtf32> -> tile<128xf64>
    %60 = reshape %59 : tile<128xf64> -> tile<1x1x128xf64>
    %61 = constant <i32: 16> : tile<i32>
    %62 = muli %26, %61 : tile<i32>
    %63 = constant <i32: 4> : tile<i32>
    %64 = addi %62, %63 : tile<i32>
    %65 = store_view_tko weak %60, %24[%9, %64, %30] token=%57 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x11x128xf64, strides=[1408, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %66 = ftof %14 rounding<zero> : tile<128xf32> -> tile<128xtf32>
    %67 = ftof %66 rounding<nearest_even> : tile<128xtf32> -> tile<128xf64>
    %68 = reshape %67 : tile<128xf64> -> tile<1x1x128xf64>
    %69 = constant <i32: 16> : tile<i32>
    %70 = muli %26, %69 : tile<i32>
    %71 = constant <i32: 5> : tile<i32>
    %72 = addi %70, %71 : tile<i32>
    %73 = store_view_tko weak %68, %24[%9, %72, %30] token=%65 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x11x128xf64, strides=[1408, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %74 = ftof %14 rounding<nearest_away> : tile<128xf32> -> tile<128xtf32>
    %75 = ftof %74 rounding<nearest_away> : tile<128xtf32> -> tile<128xf64>
    %76 = reshape %75 : tile<128xf64> -> tile<1x1x128xf64>
    %77 = constant <i32: 16> : tile<i32>
    %78 = muli %26, %77 : tile<i32>
    %79 = constant <i32: 6> : tile<i32>
    %80 = addi %78, %79 : tile<i32>
    %81 = store_view_tko weak %76, %24[%9, %80, %30] token=%73 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x11x128xf64, strides=[1408, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %82 = ftof %14 rounding<nearest_even> : tile<128xf32> -> tile<128xf16>
    %83 = ftof %82 rounding<nearest_even> : tile<128xf16> -> tile<128xf64>
    %84 = reshape %83 : tile<128xf64> -> tile<1x1x128xf64>
    %85 = constant <i32: 16> : tile<i32>
    %86 = muli %26, %85 : tile<i32>
    %87 = constant <i32: 7> : tile<i32>
    %88 = addi %86, %87 : tile<i32>
    %89 = store_view_tko weak %84, %24[%9, %88, %30] token=%81 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x11x128xf64, strides=[1408, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %90 = ftof %14 rounding<zero> : tile<128xf32> -> tile<128xf16>
    %91 = ftof %90 rounding<zero> : tile<128xf16> -> tile<128xf64>
    %92 = reshape %91 : tile<128xf64> -> tile<1x1x128xf64>
    %93 = constant <i32: 16> : tile<i32>
    %94 = muli %26, %93 : tile<i32>
    %95 = constant <i32: 8> : tile<i32>
    %96 = addi %94, %95 : tile<i32>
    %97 = store_view_tko weak %92, %24[%9, %96, %30] token=%89 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x11x128xf64, strides=[1408, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %98 = ftof %14 rounding<nearest_even> : tile<128xf32> -> tile<128xbf16>
    %99 = ftof %98 rounding<nearest_even> : tile<128xbf16> -> tile<128xf64>
    %100 = reshape %99 : tile<128xf64> -> tile<1x1x128xf64>
    %101 = constant <i32: 16> : tile<i32>
    %102 = muli %26, %101 : tile<i32>
    %103 = constant <i32: 9> : tile<i32>
    %104 = addi %102, %103 : tile<i32>
    %105 = store_view_tko weak %100, %24[%9, %104, %30] token=%97 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x11x128xf64, strides=[1408, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %106 = ftof %14 rounding<zero> : tile<128xf32> -> tile<128xbf16>
    %107 = ftof %106 rounding<positive_inf> : tile<128xbf16> -> tile<128xf64>
    %108 = reshape %107 : tile<128xf64> -> tile<1x1x128xf64>
    %109 = constant <i32: 16> : tile<i32>
    %110 = muli %26, %109 : tile<i32>
    %111 = constant <i32: 10> : tile<i32>
    %112 = addi %110, %111 : tile<i32>
    %113 = store_view_tko weak %108, %24[%9, %112, %30] token=%105 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x11x128xf64, strides=[1408, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
