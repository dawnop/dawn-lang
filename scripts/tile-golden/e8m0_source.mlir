cuda_tile.module @m {
  entry @e8m0_source(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = ftof %7 rounding<zero> : tile<128xf64> -> tile<128xf32>
    %10 = bitcast %9 : tile<128xf32> -> tile<128xi32>
    %11 = constant <i32: 2147483647> : tile<128xi32>
    %12 = andi %10, %11 : tile<128xi32>
    %13 = constant <i32: 4194304> : tile<128xi32>
    %14 = cmpi less_than %12, %13, signed : tile<128xi32> -> tile<128xi1>
    %15 = select %14, %13, %12 : tile<128xi1>, tile<128xi32>
    %16 = constant <i32: 2130706432> : tile<128xi32>
    %17 = cmpi greater_than %12, %16, signed : tile<128xi32> -> tile<128xi1>
    %18 = select %17, %16, %15 : tile<128xi1>, tile<128xi32>
    %19 = constant <i32: 2139095040> : tile<128xi32>
    %20 = cmpi greater_than %12, %19, signed : tile<128xi32> -> tile<128xi1>
    %21 = constant <i32: 2143289344> : tile<128xi32>
    %22 = select %20, %21, %18 : tile<128xi1>, tile<128xi32>
    %23 = bitcast %22 : tile<128xi32> -> tile<128xf32>
    %24 = ftof %23 rounding<zero> : tile<128xf32> -> tile<128xf8E8M0FNU>
    %25 = ftof %24 rounding<nearest_even> : tile<128xf8E8M0FNU> -> tile<128xf32>
    %26 = ftof %25 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %27 = reshape %26 : tile<128xf64> -> tile<1x128xf64>
    %28 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %29 = make_tensor_view %28, shape = [4, 512], strides = [512, 1] : tensor_view<4x512xf64, strides=[512, 1]>
    %30 = make_partition_view %29 : partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xf64, strides=[512, 1]>, dim_map=[0, 1]>
    %31, %32, %33 = get_tile_block_id : tile<i32>
    %34 = constant <i32: 4> : tile<i32>
    %35 = muli %32, %34 : tile<i32>
    %36 = store_view_tko weak %27, %30[%35, %4] token=%0 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xf64, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %37 = ftof %7 rounding<zero> : tile<128xf64> -> tile<128xf32>
    %38 = bitcast %37 : tile<128xf32> -> tile<128xi32>
    %39 = constant <i32: 2147483647> : tile<128xi32>
    %40 = andi %38, %39 : tile<128xi32>
    %41 = constant <i32: 4194304> : tile<128xi32>
    %42 = cmpi less_than %40, %41, signed : tile<128xi32> -> tile<128xi1>
    %43 = select %42, %41, %40 : tile<128xi1>, tile<128xi32>
    %44 = constant <i32: 2130706432> : tile<128xi32>
    %45 = cmpi greater_than %40, %44, signed : tile<128xi32> -> tile<128xi1>
    %46 = select %45, %44, %43 : tile<128xi1>, tile<128xi32>
    %47 = constant <i32: 2139095040> : tile<128xi32>
    %48 = cmpi greater_than %40, %47, signed : tile<128xi32> -> tile<128xi1>
    %49 = constant <i32: 2143289344> : tile<128xi32>
    %50 = select %48, %49, %46 : tile<128xi1>, tile<128xi32>
    %51 = bitcast %50 : tile<128xi32> -> tile<128xf32>
    %52 = ftof %51 rounding<zero> : tile<128xf32> -> tile<128xf8E8M0FNU>
    %53 = ftof %52 rounding<nearest_even> : tile<128xf8E8M0FNU> -> tile<128xf32>
    %54 = ftof %53 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %55 = reshape %54 : tile<128xf64> -> tile<1x128xf64>
    %56 = constant <i32: 4> : tile<i32>
    %57 = muli %32, %56 : tile<i32>
    %58 = constant <i32: 1> : tile<i32>
    %59 = addi %57, %58 : tile<i32>
    %60 = store_view_tko weak %55, %30[%59, %4] token=%36 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xf64, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %61 = ftof %7 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %62 = bitcast %61 : tile<128xf32> -> tile<128xi32>
    %63 = constant <i32: 2147483647> : tile<128xi32>
    %64 = andi %62, %63 : tile<128xi32>
    %65 = constant <i32: 4194304> : tile<128xi32>
    %66 = cmpi less_than %64, %65, signed : tile<128xi32> -> tile<128xi1>
    %67 = select %66, %65, %64 : tile<128xi1>, tile<128xi32>
    %68 = constant <i32: 2130706432> : tile<128xi32>
    %69 = cmpi greater_than %64, %68, signed : tile<128xi32> -> tile<128xi1>
    %70 = select %69, %68, %67 : tile<128xi1>, tile<128xi32>
    %71 = constant <i32: 2139095040> : tile<128xi32>
    %72 = cmpi greater_than %64, %71, signed : tile<128xi32> -> tile<128xi1>
    %73 = constant <i32: 2143289344> : tile<128xi32>
    %74 = select %72, %73, %70 : tile<128xi1>, tile<128xi32>
    %75 = bitcast %74 : tile<128xi32> -> tile<128xf32>
    %76 = ftof %75 rounding<zero> : tile<128xf32> -> tile<128xf8E8M0FNU>
    %77 = ftof %76 rounding<nearest_even> : tile<128xf8E8M0FNU> -> tile<128xf32>
    %78 = ftof %77 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %79 = reshape %78 : tile<128xf64> -> tile<1x128xf64>
    %80 = constant <i32: 4> : tile<i32>
    %81 = muli %32, %80 : tile<i32>
    %82 = constant <i32: 2> : tile<i32>
    %83 = addi %81, %82 : tile<i32>
    %84 = store_view_tko weak %79, %30[%83, %4] token=%60 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xf64, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %85 = bitcast %61 : tile<128xf32> -> tile<128xi32>
    %86 = constant <i32: 2147483647> : tile<128xi32>
    %87 = andi %85, %86 : tile<128xi32>
    %88 = constant <i32: 4194304> : tile<128xi32>
    %89 = cmpi less_than %87, %88, signed : tile<128xi32> -> tile<128xi1>
    %90 = select %89, %88, %87 : tile<128xi1>, tile<128xi32>
    %91 = constant <i32: 2130706432> : tile<128xi32>
    %92 = cmpi greater_than %87, %91, signed : tile<128xi32> -> tile<128xi1>
    %93 = select %92, %91, %90 : tile<128xi1>, tile<128xi32>
    %94 = constant <i32: 2139095040> : tile<128xi32>
    %95 = cmpi greater_than %87, %94, signed : tile<128xi32> -> tile<128xi1>
    %96 = constant <i32: 2143289344> : tile<128xi32>
    %97 = select %95, %96, %93 : tile<128xi1>, tile<128xi32>
    %98 = bitcast %97 : tile<128xi32> -> tile<128xf32>
    %99 = ftof %98 rounding<zero> : tile<128xf32> -> tile<128xf8E8M0FNU>
    %100 = ftof %99 rounding<nearest_even> : tile<128xf8E8M0FNU> -> tile<128xf32>
    %101 = ftof %100 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %102 = reshape %101 : tile<128xf64> -> tile<1x128xf64>
    %103 = constant <i32: 4> : tile<i32>
    %104 = muli %32, %103 : tile<i32>
    %105 = constant <i32: 3> : tile<i32>
    %106 = addi %104, %105 : tile<i32>
    %107 = store_view_tko weak %102, %30[%106, %4] token=%84 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xf64, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
